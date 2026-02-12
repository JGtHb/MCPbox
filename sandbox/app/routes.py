"""Sandbox API routes."""

import asyncio
import json as json_module
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import verify_api_key
from app.executor import (
    DEFAULT_ALLOWED_MODULES,
    SizeLimitedStringIO,
    create_safe_builtins,
    validate_code_safety,
)
from app.registry import tool_registry
from app.ssrf import SSRFProtectedHttpx as _BaseSsrfProtectedHttpx

logger = logging.getLogger(__name__)

# Rate limiter instance - must match main.py configuration
limiter = Limiter(key_func=get_remote_address)

# Rate limit for tool execution endpoints (more expensive operations)
TOOL_RATE_LIMIT = os.environ.get("SANDBOX_TOOL_RATE_LIMIT", "60/minute")

router = APIRouter(dependencies=[Depends(verify_api_key)])


# --- Request/Response Models ---


# Maximum size limits for code fields (100KB each)
MAX_CODE_SIZE = 100 * 1024  # 100KB


class ToolDef(BaseModel):
    """Tool definition for registration.

    Tools use Python code with async main() function for execution.
    """

    name: str
    description: str = ""
    parameters: dict[str, Any] = {}
    python_code: str
    timeout_ms: int = 30000

    def model_post_init(self, __context: Any) -> None:
        """Validate code size limits after model initialization."""
        if len(self.python_code) > MAX_CODE_SIZE:
            raise ValueError(
                f"python_code exceeds maximum size of {MAX_CODE_SIZE} bytes"
            )


class CredentialDef(BaseModel):
    """Credential definition with auth type metadata."""

    name: str
    auth_type: str
    header_name: Optional[str] = None
    query_param_name: Optional[str] = None
    value: Optional[str] = None  # Encrypted
    username: Optional[str] = None  # Encrypted (for basic auth)
    password: Optional[str] = None  # Encrypted (for basic auth)


class RegisterServerRequest(BaseModel):
    """Request to register a server with tools."""

    server_id: str
    server_name: str
    tools: list[ToolDef]
    credentials: list[CredentialDef] = []
    helper_code: Optional[str] = None
    allowed_modules: Optional[list[str]] = (
        None  # Custom allowed modules (None = defaults)
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate helper_code size limit after model initialization."""
        if self.helper_code and len(self.helper_code) > MAX_CODE_SIZE:
            raise ValueError(
                f"helper_code exceeds maximum size of {MAX_CODE_SIZE} bytes"
            )


class RegisterServerResponse(BaseModel):
    """Response from server registration."""

    success: bool
    server_id: str
    tools_registered: int


class UnregisterServerResponse(BaseModel):
    """Response from server unregistration."""

    success: bool
    server_id: str


class ToolCallRequest(BaseModel):
    """Request to execute a tool."""

    arguments: dict[str, Any] = {}
    debug_mode: bool = False


class ErrorDetailResponse(BaseModel):
    """Detailed error information for debugging."""

    message: str
    error_type: str
    line_number: Optional[int] = None
    code_context: list[str] = []
    traceback: list[str] = []
    source_file: str = "<tool>"


class HttpCallInfoResponse(BaseModel):
    """Information about an HTTP call."""

    method: str
    url: str
    status_code: Optional[int] = None
    duration_ms: int = 0
    request_headers: Optional[dict[str, str]] = None
    response_preview: Optional[str] = None
    error: Optional[str] = None


class DebugInfoResponse(BaseModel):
    """Debug information from execution."""

    http_calls: list[HttpCallInfoResponse] = []
    timing_breakdown: dict[str, int] = {}


class ToolCallResponse(BaseModel):
    """Response from tool execution."""

    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    error_detail: Optional[ErrorDetailResponse] = None
    status_code: Optional[int] = None
    stdout: Optional[str] = None
    duration_ms: Optional[int] = None
    debug_info: Optional[DebugInfoResponse] = None


class ToolInfo(BaseModel):
    """Tool information."""

    name: str
    description: str
    inputSchema: dict[str, Any]


class ListToolsResponse(BaseModel):
    """Response listing all tools."""

    tools: list[ToolInfo]
    total: int


class ServerInfo(BaseModel):
    """Server information."""

    server_id: str
    server_name: str
    tool_count: int


class ListServersResponse(BaseModel):
    """Response listing all servers."""

    servers: list[ServerInfo]
    total: int


# --- Lifecycle Endpoints ---


def initialize_encryption():
    """Initialize encryption key from environment.

    Called from the lifespan handler in main.py.
    """
    encryption_key = os.environ.get("MCPBOX_ENCRYPTION_KEY")
    if encryption_key:
        tool_registry.set_encryption_key(encryption_key)
        logger.info("Encryption key configured for credential decryption")


# --- Server Management ---


@router.post("/servers/register", response_model=RegisterServerResponse)
async def register_server(request: RegisterServerRequest):
    """Register a server with its tools.

    This makes the server's tools available for execution.
    If the server is already registered, it will be re-registered.

    Tools use Python code with async main() function for execution.
    """
    tools_data = []

    for t in request.tools:
        tool_data = {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
            "python_code": t.python_code,
            "timeout_ms": t.timeout_ms,
        }
        tools_data.append(tool_data)

    # Convert credentials to list of dicts
    credentials_data = [
        {
            "name": c.name,
            "auth_type": c.auth_type,
            "header_name": c.header_name,
            "query_param_name": c.query_param_name,
            "value": c.value,
            "username": c.username,
            "password": c.password,
        }
        for c in request.credentials
    ]

    count = tool_registry.register_server(
        server_id=request.server_id,
        server_name=request.server_name,
        tools=tools_data,
        credentials=credentials_data,
        helper_code=request.helper_code,
        allowed_modules=request.allowed_modules,
    )

    return RegisterServerResponse(
        success=True,
        server_id=request.server_id,
        tools_registered=count,
    )


@router.post("/servers/{server_id}/unregister", response_model=UnregisterServerResponse)
async def unregister_server(server_id: str):
    """Unregister a server and remove all its tools."""
    success = tool_registry.unregister_server(server_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server not found: {server_id}",
        )

    return UnregisterServerResponse(success=True, server_id=server_id)


@router.get("/servers", response_model=ListServersResponse)
async def list_servers():
    """List all registered servers."""
    servers = [
        ServerInfo(
            server_id=s.server_id,
            server_name=s.server_name,
            tool_count=len(s.tools),
        )
        for s in tool_registry.servers.values()
    ]

    return ListServersResponse(servers=servers, total=len(servers))


# --- Tool Management ---


@router.get("/tools", response_model=ListToolsResponse)
async def list_tools(server_id: Optional[str] = None):
    """List all registered tools.

    Optionally filter by server_id.
    """
    if server_id:
        tools = tool_registry.list_tools_for_server(server_id)
    else:
        tools = tool_registry.list_tools()

    return ListToolsResponse(
        tools=[ToolInfo(**t) for t in tools],
        total=len(tools),
    )


@router.post("/tools/{tool_name}/call", response_model=ToolCallResponse)
@limiter.limit(TOOL_RATE_LIMIT)
async def call_tool(request: Request, tool_name: str, body: ToolCallRequest):
    """Execute a tool with the given arguments.

    tool_name should be the full name: servername__toolname

    For python_code tools, the response includes stdout and duration_ms.
    Set debug_mode=true for detailed execution info.
    """
    start_time = time.monotonic()

    # Log tool execution start
    logger.info(
        f"Tool execution started: {tool_name}",
        extra={
            "tool_name": tool_name,
            "debug_mode": body.debug_mode,
            "argument_keys": list(body.arguments.keys()),
        },
    )

    result = await tool_registry.execute_tool(
        tool_name,
        body.arguments,
        debug_mode=body.debug_mode,
    )

    # Calculate duration
    duration_ms = int((time.monotonic() - start_time) * 1000)

    # Log tool execution result
    if result.get("success"):
        logger.info(
            f"Tool execution completed: {tool_name} ({duration_ms}ms)",
            extra={
                "tool_name": tool_name,
                "success": True,
                "duration_ms": duration_ms,
                "status_code": result.get("status_code"),
            },
        )
    else:
        logger.warning(
            f"Tool execution failed: {tool_name} ({duration_ms}ms) - {result.get('error', 'unknown error')}",
            extra={
                "tool_name": tool_name,
                "success": False,
                "duration_ms": duration_ms,
                "error": result.get("error"),
            },
        )

    # Build error_detail response if present
    error_detail = None
    if result.get("error_detail"):
        ed = result["error_detail"]
        error_detail = ErrorDetailResponse(
            message=ed.get("message", ""),
            error_type=ed.get("error_type", "Error"),
            line_number=ed.get("line_number"),
            code_context=ed.get("code_context", []),
            traceback=ed.get("traceback", []),
            source_file=ed.get("source_file", "<tool>"),
        )

    # Build debug_info response if present
    debug_info = None
    if result.get("debug_info"):
        di = result["debug_info"]
        http_calls = [HttpCallInfoResponse(**call) for call in di.get("http_calls", [])]
        debug_info = DebugInfoResponse(
            http_calls=http_calls,
            timing_breakdown=di.get("timing_breakdown", {}),
        )

    return ToolCallResponse(
        success=result.get("success", False),
        result=result.get("result"),
        error=result.get("error"),
        error_detail=error_detail,
        status_code=result.get("status_code"),
        stdout=result.get("stdout"),
        duration_ms=result.get("duration_ms"),
        debug_info=debug_info,
    )


# --- MCP Protocol Endpoints ---


@router.post("/mcp")
@limiter.limit(TOOL_RATE_LIMIT)
async def mcp_endpoint(request: Request, body: dict[str, Any]):
    """MCP JSON-RPC endpoint.

    Handles tools/list and tools/call methods.
    """
    method = body.get("method")
    params = body.get("params", {})
    request_id = body.get("id")

    # Log MCP request
    logger.info(
        f"MCP request: {method}", extra={"method": method, "request_id": request_id}
    )

    if method == "tools/list":
        tools = tool_registry.list_tools()
        logger.info(f"MCP tools/list: returning {len(tools)} tools")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tools},
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            logger.warning("MCP tools/call: missing tool name")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": "Missing tool name",
                },
            }

        start_time = time.monotonic()
        result = await tool_registry.execute_tool(tool_name, arguments)
        duration_ms = int((time.monotonic() - start_time) * 1000)

        # Log execution result
        if result.get("success"):
            logger.info(
                f"MCP tools/call: {tool_name} succeeded ({duration_ms}ms)",
                extra={"tool_name": tool_name, "duration_ms": duration_ms},
            )
        else:
            logger.warning(
                f"MCP tools/call: {tool_name} failed ({duration_ms}ms) - {result.get('error')}",
                extra={
                    "tool_name": tool_name,
                    "duration_ms": duration_ms,
                    "error": result.get("error"),
                },
            )

        if result.get("success"):
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": str(result.get("result", "")),
                        }
                    ]
                },
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32000,
                    "message": result.get("error", "Unknown error"),
                },
            }

    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}",
            },
        }


# --- Python Code Execution (Direct Endpoint for Testing) ---


class ExecuteCodeRequest(BaseModel):
    """Request to execute Python code directly."""

    code: str
    arguments: dict[str, Any] = {}
    credentials: dict[str, str] = {}
    timeout_seconds: int = 30
    allowed_modules: Optional[list[str]] = (
        None  # Custom allowed modules (None = defaults)
    )


class ExecuteCodeResponse(BaseModel):
    """Response from code execution."""

    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    stdout: Optional[str] = None


# Safe builtins are provided by create_safe_builtins() from executor.py
# (single source of truth — do NOT duplicate the builtin list here)


# SSRFProtectedHttpx (_BaseSsrfProtectedHttpx) is imported at the top of the file


class SSRFProtectedHttpx(_BaseSsrfProtectedHttpx):
    """SSRF-protected wrapper for httpx module with client creation blocking.

    Extends the base SSRFProtectedHttpx to also block direct Client/AsyncClient creation.
    """

    # Block direct client creation - users must use the protected methods
    @staticmethod
    def Client(*args, **kwargs):
        raise ValueError(
            "Direct Client creation is not allowed. Use httpx.get(), httpx.post(), etc."
        )

    @staticmethod
    def AsyncClient(*args, **kwargs):
        raise ValueError(
            "Direct AsyncClient creation is not allowed. Use httpx.get(), httpx.post(), etc."
        )


# Singleton instance for the execute endpoint
_ssrf_protected_httpx = SSRFProtectedHttpx()


class IsolatedEnv:
    """Isolated environment that only exposes provided credentials.

    Prevents credential leakage between requests by not touching global os.environ.
    """

    def __init__(self, credentials: dict[str, str]):
        self._env = credentials.copy()

    def get(self, key: str, default: str = None) -> Optional[str]:
        """Get an environment variable from the isolated env."""
        return self._env.get(key, default)

    def __getitem__(self, key: str) -> str:
        """Get an environment variable, raises KeyError if not found."""
        if key not in self._env:
            raise KeyError(key)
        return self._env[key]

    def __contains__(self, key: str) -> bool:
        """Check if key exists in isolated env."""
        return key in self._env

    def keys(self):
        """Return keys in isolated env."""
        return self._env.keys()

    def values(self):
        """Return values in isolated env."""
        return self._env.values()

    def items(self):
        """Return items in isolated env."""
        return self._env.items()


class IsolatedOs:
    """Isolated os module that only provides safe, sandboxed access.

    This class explicitly blocks all os module functionality except for
    safe environment variable access. Any attempt to access other attributes
    (like path, system, getcwd, etc.) will raise an AttributeError.
    """

    # Explicitly define allowed attributes to prevent __getattr__ bypass
    __slots__ = ("environ", "_credentials")

    def __init__(self, credentials: dict[str, str]):
        object.__setattr__(self, "_credentials", credentials)
        object.__setattr__(self, "environ", IsolatedEnv(credentials))

    def getenv(self, key: str, default: str = None) -> Optional[str]:
        """Get environment variable from isolated env."""
        return self.environ.get(key, default)

    def __getattr__(self, name: str):
        """Block access to any os attributes not explicitly defined."""
        raise AttributeError(
            f"'os' module attribute '{name}' is not available in the sandbox. "
            "Only os.environ and os.getenv() are allowed."
        )

    def __setattr__(self, name: str, value):
        """Prevent setting arbitrary attributes."""
        raise AttributeError("Cannot set attributes on sandboxed os module")

    def __delattr__(self, name: str):
        """Prevent deleting attributes."""
        raise AttributeError("Cannot delete attributes on sandboxed os module")


@router.post("/execute", response_model=ExecuteCodeResponse)
@limiter.limit(TOOL_RATE_LIMIT)
async def execute_python_code(request: Request, body: ExecuteCodeRequest):
    """Execute Python code in a sandboxed environment.

    This endpoint provides direct code execution for testing.
    For production use, register tools and use the /tools/{name}/call endpoint.

    The code runs in an isolated namespace with:
    - Limited builtins (no file/network access from builtins)
    - Access to httpx for HTTP requests
    - Access to json for JSON parsing
    - Credentials available via isolated os.environ (NOT the real os.environ)

    The code must set a 'result' variable to return data.

    Security:
    - Credentials are injected into an isolated environment, NOT the global os.environ
    - Code cannot access credentials from other requests
    - Code cannot access the real system environment
    """
    # Validate code length
    if len(body.code) > 50000:
        return ExecuteCodeResponse(
            success=False,
            error="Code too long (max 50,000 characters)",
        )

    # SECURITY: Validate code safety before execution
    # This checks for sandbox escape patterns like __class__, __mro__, __subclasses__, etc.
    is_safe, error_msg = validate_code_safety(body.code, "<execute>")
    if not is_safe:
        return ExecuteCodeResponse(
            success=False,
            error=f"Code safety validation failed: {error_msg}",
        )

    # Validate timeout bounds (1 second to 5 minutes max)
    timeout_seconds = max(1, min(body.timeout_seconds, 300))

    # Create isolated os module with ONLY the provided credentials
    # This prevents leakage of credentials between requests and
    # prevents access to the real system environment
    isolated_os = IsolatedOs(body.credentials)

    # Determine effective allowed modules (admin-configured whitelist)
    allowed_modules_set = (
        set(body.allowed_modules) if body.allowed_modules else DEFAULT_ALLOWED_MODULES
    )

    # Create builtins using the shared function (single source of truth)
    safe_builtins_with_import = create_safe_builtins(
        allowed_modules=allowed_modules_set
    )

    # Create isolated namespace
    # NOTE: httpx is wrapped with SSRF protection to prevent access to internal IPs
    namespace = {
        "__builtins__": safe_builtins_with_import,
        "httpx": _ssrf_protected_httpx,
        "json": json_module,
        "os": isolated_os,
        "arguments": body.arguments,
        "result": None,
    }

    # Capture stdout (size-limited to prevent memory exhaustion)
    stdout_capture = SizeLimitedStringIO()

    def execute_code_sync() -> None:
        """Execute code synchronously in a thread."""
        with redirect_stdout(stdout_capture):
            exec(body.code, namespace)

    # Execute with asyncio timeout (cross-platform, no race conditions)
    try:
        loop = asyncio.get_running_loop()
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                await asyncio.wait_for(
                    loop.run_in_executor(executor, execute_code_sync),
                    timeout=timeout_seconds,
                )
        except RuntimeError as thread_err:
            # Thread creation failed (e.g., in restricted CI environments)
            # Fall back to synchronous execution with signal-based timeout
            if "can't start new thread" in str(thread_err):
                logger.warning(
                    "Threading unavailable, falling back to synchronous execution with signal timeout"
                )
                import signal
                import threading

                def timeout_handler(signum, frame):
                    raise TimeoutError(
                        f"Execution timed out after {timeout_seconds} seconds"
                    )

                # Signal-based timeout only works in the main thread
                if threading.current_thread() is threading.main_thread():
                    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(int(timeout_seconds))
                    try:
                        execute_code_sync()
                    finally:
                        signal.alarm(0)  # Cancel the alarm
                        signal.signal(signal.SIGALRM, old_handler)
                else:
                    # Not in main thread (e.g., pytest worker) - execute without signal timeout
                    # This is acceptable because the ThreadPoolExecutor with asyncio.wait_for
                    # is the primary timeout mechanism; this is just a fallback
                    logger.warning(
                        "Signal timeout unavailable (not in main thread), executing without timeout"
                    )
                    execute_code_sync()
            else:
                raise

    except asyncio.TimeoutError:
        return ExecuteCodeResponse(
            success=False,
            error=f"Execution timed out after {timeout_seconds} seconds",
            stdout=stdout_capture.getvalue()[:10000],
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
        ZeroDivisionError,
        SyntaxError,
        ImportError,
        NameError,
        StopIteration,
        ArithmeticError,
        LookupError,
    ) as e:
        # Known safe exceptions — return details to help debugging
        return ExecuteCodeResponse(
            success=False,
            error=f"Execution error: {type(e).__name__}: {str(e)}",
            stdout=stdout_capture.getvalue()[:10000],
        )
    except Exception:
        # Unexpected exceptions — return generic message to avoid leaking internals
        return ExecuteCodeResponse(
            success=False,
            error="Execution failed due to an internal error",
            stdout=stdout_capture.getvalue()[:10000],
        )

    # Get result
    result = namespace.get("result")

    return ExecuteCodeResponse(
        success=True,
        result=result,
        stdout=stdout_capture.getvalue()[:10000],  # Limit stdout
    )


# Note: Health check is defined in main.py at /health (without auth requirement)
# This allows load balancers to check health without needing API credentials.


# --- Package Management Endpoints ---


class PackageInstallRequest(BaseModel):
    """Request to install a package."""

    module_name: str
    version: Optional[str] = None


class PackageInstallResponse(BaseModel):
    """Response from package installation."""

    module_name: str
    package_name: str
    status: str
    version: Optional[str] = None
    error_message: Optional[str] = None


class PackageSyncRequest(BaseModel):
    """Request to sync packages with backend module list."""

    modules: list[str]


class PackageSyncResponse(BaseModel):
    """Response from package sync."""

    results: list[PackageInstallResponse]
    installed_count: int
    failed_count: int
    stdlib_count: int


class PackageStatusResponse(BaseModel):
    """Response for package status check."""

    module_name: str
    package_name: str
    is_stdlib: bool
    is_installed: bool
    installed_version: Optional[str] = None


class PackageListResponse(BaseModel):
    """Response listing installed packages."""

    packages: list[dict[str, str]]
    total: int


class ModuleClassifyRequest(BaseModel):
    """Request to classify modules as stdlib or third-party."""

    modules: list[str]


class ModuleClassifyResponse(BaseModel):
    """Response from module classification."""

    stdlib: list[str]
    third_party: list[str]


class PyPIInfoRequest(BaseModel):
    """Request for PyPI package information."""

    module_name: str


class PyPIInfoResponse(BaseModel):
    """Response with PyPI package information and safety data."""

    module_name: str
    package_name: str
    is_stdlib: bool
    pypi_info: Optional[dict] = None
    # Safety data from external sources (OSV.dev, deps.dev)
    vulnerabilities: list[dict] = []
    vulnerability_count: int = 0
    scorecard_score: Optional[float] = None
    scorecard_date: Optional[str] = None
    dependency_count: Optional[int] = None
    source_repo: Optional[str] = None
    error: Optional[str] = None


@router.post("/packages/install", response_model=PackageInstallResponse)
async def install_package_endpoint(body: PackageInstallRequest):
    """Install a single package.

    Installs the package to the persistent packages directory.
    Stdlib modules return status 'not_required'.
    """
    from app.package_installer import install_package, install_result_to_dict

    result = await install_package(body.module_name, body.version)
    data = install_result_to_dict(result)

    return PackageInstallResponse(**data)


@router.post("/packages/sync", response_model=PackageSyncResponse)
async def sync_packages_endpoint(body: PackageSyncRequest):
    """Sync packages with the backend module list.

    Installs any missing third-party packages.
    Returns summary of installation results.
    """
    from app.package_installer import (
        install_packages,
        install_result_to_dict,
        InstallStatus,
    )

    results = await install_packages(body.modules)

    installed_count = sum(1 for r in results if r.status == InstallStatus.INSTALLED)
    failed_count = sum(1 for r in results if r.status == InstallStatus.FAILED)
    stdlib_count = sum(1 for r in results if r.status == InstallStatus.NOT_REQUIRED)

    return PackageSyncResponse(
        results=[PackageInstallResponse(**install_result_to_dict(r)) for r in results],
        installed_count=installed_count,
        failed_count=failed_count,
        stdlib_count=stdlib_count,
    )


@router.get("/packages/status/{module_name}", response_model=PackageStatusResponse)
async def get_package_status(module_name: str):
    """Get the installation status of a module.

    Returns whether it's stdlib, installed, and version info.
    """
    from app.stdlib_detector import is_stdlib_module
    from app.pypi_client import get_package_name_for_module
    from app.package_installer import is_package_installed

    is_stdlib = is_stdlib_module(module_name)
    package_name = await get_package_name_for_module(module_name)

    if is_stdlib:
        return PackageStatusResponse(
            module_name=module_name,
            package_name=module_name,
            is_stdlib=True,
            is_installed=True,  # stdlib is always available
            installed_version=None,
        )

    installed, version = is_package_installed(package_name)

    return PackageStatusResponse(
        module_name=module_name,
        package_name=package_name,
        is_stdlib=False,
        is_installed=installed,
        installed_version=version,
    )


@router.get("/packages", response_model=PackageListResponse)
async def list_installed_packages_endpoint():
    """List all packages installed in the custom packages directory."""
    from app.package_installer import list_installed_packages

    packages = list_installed_packages()

    return PackageListResponse(
        packages=packages,
        total=len(packages),
    )


@router.post("/packages/classify", response_model=ModuleClassifyResponse)
async def classify_modules_endpoint(body: ModuleClassifyRequest):
    """Classify modules as stdlib or third-party."""
    from app.stdlib_detector import classify_modules

    result = classify_modules(body.modules)

    return ModuleClassifyResponse(
        stdlib=result["stdlib"],
        third_party=result["third_party"],
    )


@router.post("/packages/pypi-info", response_model=PyPIInfoResponse)
async def get_pypi_info_endpoint(body: PyPIInfoRequest):
    """Get PyPI information and safety data for a module.

    Returns package metadata from PyPI, known vulnerabilities from OSV.dev,
    and project health from deps.dev. Stdlib modules skip safety checks.
    """
    from app.stdlib_detector import is_stdlib_module
    from app.pypi_client import fetch_module_info, package_info_to_dict

    is_stdlib = is_stdlib_module(body.module_name)

    if is_stdlib:
        return PyPIInfoResponse(
            module_name=body.module_name,
            package_name=body.module_name,
            is_stdlib=True,
            pypi_info=None,
        )

    try:
        package_name, info = await fetch_module_info(body.module_name)

        if info is None:
            return PyPIInfoResponse(
                module_name=body.module_name,
                package_name=package_name,
                is_stdlib=False,
                pypi_info=None,
                error=f"Package '{package_name}' not found on PyPI",
            )

        # Fetch safety data in parallel (non-blocking, failures don't break response)
        from app.osv_client import fetch_vulnerabilities
        from app.deps_client import fetch_deps_info

        vuln_results, deps_info = await asyncio.gather(
            fetch_vulnerabilities(package_name),
            fetch_deps_info(package_name, info.version if info else None),
            return_exceptions=True,
        )

        # Handle vulnerabilities (graceful on error)
        vulns: list[dict] = []
        if isinstance(vuln_results, list):
            vulns = [v.to_dict() for v in vuln_results]
        elif isinstance(vuln_results, Exception):
            logger.warning(
                "OSV.dev lookup failed for %s: %s", package_name, vuln_results
            )

        # Handle deps.dev info (graceful on error)
        scorecard_score = None
        scorecard_date = None
        dependency_count = None
        source_repo = None
        if not isinstance(deps_info, Exception) and deps_info is not None:
            scorecard_score = deps_info.scorecard_score
            scorecard_date = deps_info.scorecard_date
            dependency_count = deps_info.dependency_count
            source_repo = deps_info.source_repo
        elif isinstance(deps_info, Exception):
            logger.warning("deps.dev lookup failed for %s: %s", package_name, deps_info)

        return PyPIInfoResponse(
            module_name=body.module_name,
            package_name=package_name,
            is_stdlib=False,
            pypi_info=package_info_to_dict(info),
            vulnerabilities=vulns,
            vulnerability_count=len(vulns),
            scorecard_score=scorecard_score,
            scorecard_date=scorecard_date,
            dependency_count=dependency_count,
            source_repo=source_repo,
        )
    except Exception as e:
        return PyPIInfoResponse(
            module_name=body.module_name,
            package_name=body.module_name,
            is_stdlib=False,
            error=str(e),
        )
