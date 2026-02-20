"""Sandbox API routes."""

import asyncio
import datetime as datetime_module
import json as json_module
import logging
import os
import time

from contextlib import redirect_stdout
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import verify_api_key
from app.executor import (
    DEFAULT_ALLOWED_MODULES,
    SafeModuleProxy,
    SizeLimitedStringIO,
    create_safe_builtins,
    validate_code_safety,
)
from app.registry import tool_registry
from app.ssrf import SSRFError
from app.ssrf import SSRFProtectedAsyncHttpClient
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
    python_code: Optional[str] = (
        None  # Required for python_code tools, None for passthrough
    )
    timeout_ms: int = 30000
    tool_type: str = "python_code"
    external_source_id: Optional[str] = None
    external_tool_name: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        """Validate code size limits after model initialization."""
        if self.python_code and len(self.python_code) > MAX_CODE_SIZE:
            raise ValueError(
                f"python_code exceeds maximum size of {MAX_CODE_SIZE} bytes"
            )


class ExternalSourceDef(BaseModel):
    """External MCP source definition for server registration."""

    source_id: str
    url: str
    auth_headers: dict[str, str] = {}
    transport_type: str = "streamable_http"


class RegisterServerRequest(BaseModel):
    """Request to register a server with tools."""

    server_id: str
    server_name: str
    tools: list[ToolDef]
    allowed_modules: Optional[list[str]] = (
        None  # Custom allowed modules (None = defaults)
    )
    secrets: dict[str, str] = {}  # Key-value secrets for injection into tool namespace
    external_sources: list[ExternalSourceDef] = []  # External MCP source configs
    # Network access control: approved hostnames (None = no restriction)
    allowed_hosts: Optional[list[str]] = None


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


# --- Server Management ---


@router.post("/servers/register", response_model=RegisterServerResponse)
async def register_server(request: RegisterServerRequest):
    """Register a server with its tools.

    This makes the server's tools available for execution.
    If the server is already registered, it will be re-registered.

    Tools can be Python code (with async main() function) or MCP passthrough.
    """
    tools_data = []

    for t in request.tools:
        tool_data = {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
            "python_code": t.python_code,
            "timeout_ms": t.timeout_ms,
            "tool_type": t.tool_type,
            "external_source_id": t.external_source_id,
            "external_tool_name": t.external_tool_name,
        }
        tools_data.append(tool_data)

    # Build external source configs
    external_sources_data = [
        {
            "source_id": s.source_id,
            "url": s.url,
            "auth_headers": s.auth_headers,
            "transport_type": s.transport_type,
        }
        for s in request.external_sources
    ]

    count = tool_registry.register_server(
        server_id=request.server_id,
        server_name=request.server_name,
        tools=tools_data,
        allowed_modules=request.allowed_modules,
        secrets=request.secrets,
        external_sources=external_sources_data,
        allowed_hosts=request.allowed_hosts,
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


class UpdateSecretsRequest(BaseModel):
    """Request to update secrets for a running server."""

    secrets: dict[str, str] = {}


class UpdateSecretsResponse(BaseModel):
    """Response from updating server secrets."""

    success: bool
    server_id: str


@router.put("/servers/{server_id}/secrets", response_model=UpdateSecretsResponse)
async def update_server_secrets(server_id: str, body: UpdateSecretsRequest):
    """Update secrets for a running server.

    Replaces the server's secrets with the provided dict.
    Called by the backend when an admin sets, updates, or deletes a secret
    so the sandbox always has current decrypted values.
    """
    success = tool_registry.update_secrets(server_id, body.secrets)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server not found: {server_id}",
        )

    return UpdateSecretsResponse(success=True, server_id=server_id)


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
                    ],
                    "isError": False,
                },
            }
        else:
            # Per MCP spec, tool execution failures MUST be returned as
            # result with isError:true (not JSON-RPC error). Only JSON-RPC
            # errors are for protocol-level issues (unknown tool, malformed
            # request). Clients SHOULD show isError results to the LLM.
            error_parts = []

            # Primary error message
            error_msg = result.get("error", "Unknown error")
            error_parts.append(error_msg)

            # Append stdout if present (tool may have printed debug info)
            stdout = result.get("stdout", "")
            if stdout and stdout.strip():
                error_parts.append(f"\n--- stdout ---\n{stdout.strip()}")

            # Append structured error detail if present
            error_detail = result.get("error_detail")
            if error_detail:
                detail_lines = []
                if error_detail.get("error_type"):
                    detail_lines.append(f"Error type: {error_detail['error_type']}")
                if error_detail.get("line_number"):
                    detail_lines.append(f"Line: {error_detail['line_number']}")
                if error_detail.get("code_context"):
                    detail_lines.append("Context:")
                    for ctx_line in error_detail["code_context"]:
                        detail_lines.append(f"  {ctx_line}")
                if error_detail.get("http_info"):
                    hi = error_detail["http_info"]
                    if hi.get("status_code"):
                        detail_lines.append(
                            f"HTTP {hi['status_code']} from {hi.get('url', 'unknown')}"
                        )
                    if hi.get("response_headers"):
                        for k, v in hi["response_headers"].items():
                            detail_lines.append(f"  {k}: {v}")
                    if hi.get("body_preview"):
                        detail_lines.append(
                            f"Response preview: {hi['body_preview'][:300]}"
                        )
                if detail_lines:
                    error_parts.append("\n--- detail ---\n" + "\n".join(detail_lines))

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "\n".join(error_parts),
                        }
                    ],
                    "isError": True,
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


# --- External MCP Discovery ---


class MCPDiscoverRequest(BaseModel):
    """Request to discover tools from an external MCP server."""

    url: str
    transport_type: str = "streamable_http"
    auth_headers: dict[str, str] = {}


class MCPDiscoverResponse(BaseModel):
    """Response from external MCP tool discovery."""

    success: bool
    tools: list[dict[str, Any]] = []
    error: Optional[str] = None


@router.post("/mcp-discover", response_model=MCPDiscoverResponse)
async def discover_external_tools(body: MCPDiscoverRequest):
    """Discover tools from an external MCP server.

    Uses the MCP session pool for connection reuse and automatic retry
    on transient errors.
    """
    from app.mcp_session_pool import mcp_session_pool

    result = await mcp_session_pool.discover_tools(
        url=body.url,
        auth_headers=body.auth_headers,
    )

    return MCPDiscoverResponse(
        success=result.get("success", False),
        tools=result.get("tools", []),
        error=result.get("error"),
    )


class ExternalHealthCheckRequest(BaseModel):
    """Request to check connectivity to an external MCP server."""

    url: str
    auth_headers: dict[str, str] = {}


class ExternalHealthCheckResponse(BaseModel):
    """Response from external MCP server health check."""

    healthy: bool
    latency_ms: int = 0
    error: Optional[str] = None


@router.post("/mcp-health-check", response_model=ExternalHealthCheckResponse)
async def check_external_health(body: ExternalHealthCheckRequest):
    """Check connectivity to an external MCP server.

    Performs an MCP initialize handshake to verify the server is reachable
    and responding to MCP protocol requests.
    """
    from app.mcp_session_pool import mcp_session_pool

    result = await mcp_session_pool.health_check(
        url=body.url,
        auth_headers=body.auth_headers,
    )

    return ExternalHealthCheckResponse(
        healthy=result.get("healthy", False),
        latency_ms=result.get("latency_ms", 0),
        error=result.get("error"),
    )


class SessionPoolStatsResponse(BaseModel):
    """Response with MCP session pool statistics."""

    pool_size: int
    max_size: int
    sessions: list[dict[str, Any]] = []


@router.get("/mcp-pool-stats", response_model=SessionPoolStatsResponse)
async def get_pool_stats():
    """Get MCP session pool statistics for monitoring."""
    from app.mcp_session_pool import mcp_session_pool

    stats = mcp_session_pool.stats()
    return SessionPoolStatsResponse(**stats)


# --- Python Code Execution (Direct Endpoint for Testing) ---


class ExecuteCodeRequest(BaseModel):
    """Request to execute Python code directly."""

    code: str
    arguments: dict[str, Any] = {}
    credentials: dict[str, str] = {}
    timeout_seconds: int = 30
    # Admin-configured module allowlist injected by the backend (SEC-015).
    # The LLM cannot set this directly — the backend fetches it from the DB
    # and passes it here, so test_code always reflects the live approved list.
    # None = fall back to DEFAULT_ALLOWED_MODULES (safe default).
    allowed_modules: Optional[list[str]] = None
    secrets: dict[str, str] = {}  # Key-value secrets for injection into namespace
    # Per-server network host allowlist — mirrors production tool execution.
    # None = global SSRF protection only (any public host allowed).
    # [] = block all outbound network access.
    # ["api.example.com"] = only that host is reachable.
    allowed_hosts: Optional[list[str]] = None


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
    - Secrets available via read-only `secrets` dict

    The code must set a 'result' variable to return data.

    Security:
    - Secrets are injected as a read-only MappingProxyType
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

    # Use backend-supplied module list when provided (SEC-015: the backend
    # fetches this from the DB, so it reflects the live admin-approved list).
    # Fall back to DEFAULT_ALLOWED_MODULES when not provided.
    allowed_modules_set = (
        set(body.allowed_modules)
        if body.allowed_modules is not None
        else DEFAULT_ALLOWED_MODULES
    )

    # Create builtins using the shared function (single source of truth)
    safe_builtins_with_import = create_safe_builtins(
        allowed_modules=allowed_modules_set
    )

    # Create isolated namespace matching published tool environment
    # This ensures test_code results match production behavior
    from types import MappingProxyType

    namespace = {
        "__builtins__": safe_builtins_with_import,
        # Wrap modules with SafeModuleProxy to prevent attribute traversal
        # (e.g., datetime.sys.modules["os"].popen("id"))
        "json": SafeModuleProxy(json_module, name="json"),
        "datetime": SafeModuleProxy(datetime_module, name="datetime"),
        "arguments": body.arguments,
        "secrets": MappingProxyType(body.secrets),  # Read-only secrets dict
        "result": None,
    }

    # Capture stdout (size-limited to prevent memory exhaustion)
    stdout_capture = SizeLimitedStringIO()

    # Phase 1: exec() the code to define functions (synchronous, just defines main())
    # Phase 2: If async main() is defined, create http client on THIS loop and await it
    # This mirrors PythonExecutor.execute() which does exec() then await main_func()
    _http_client = None
    try:
        try:
            # Phase 1: Define functions by executing the code
            with redirect_stdout(stdout_capture):
                exec(body.code, namespace)

            # Phase 2: Check if an async main() was defined
            main_func = namespace.get("main")
            if main_func is not None and asyncio.iscoroutinefunction(main_func):
                # Create SSRF-protected HTTP client on the CURRENT event loop
                # (same loop we'll await main() on — avoids event loop affinity issues).
                # Pass allowed_hosts to enforce the same per-server network allowlist
                # as production tool execution (None = global SSRF only).
                _http_client = httpx.AsyncClient()
                _allowed_hosts = (
                    set(body.allowed_hosts) if body.allowed_hosts is not None else None
                )
                _protected_http = SSRFProtectedAsyncHttpClient(
                    _http_client, allowed_hosts=_allowed_hosts
                )
                namespace["http"] = _protected_http

                # Await main() directly on this event loop (matches production executor)
                result = await asyncio.wait_for(
                    main_func(**body.arguments),
                    timeout=timeout_seconds,
                )
                namespace["result"] = result
            elif main_func is not None and callable(main_func):
                # Synchronous main() — call it directly
                result = main_func(**body.arguments)
                namespace["result"] = result

        except asyncio.TimeoutError:
            return ExecuteCodeResponse(
                success=False,
                error=f"Execution timed out after {timeout_seconds} seconds",
                stdout=stdout_capture.getvalue()[:10000],
            )
        except SSRFError as e:
            # Network access blocked — surface the specific host and hint so the
            # LLM can immediately call mcpbox_request_network_access rather than
            # guessing why the HTTP call failed silently.
            return ExecuteCodeResponse(
                success=False,
                error=f"Network access blocked: {e}",
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
        except Exception as e:
            # Unknown/unexpected exceptions may contain sensitive internal details
            # (e.g., database connection strings, file paths, infrastructure info).
            # Return a generic error message and log the real error server-side.
            logger.error(f"Unexpected execution error: {type(e).__name__}: {e}")
            return ExecuteCodeResponse(
                success=False,
                error="An internal error occurred during code execution",
                stdout=stdout_capture.getvalue()[:10000],
            )

        # Get result
        result = namespace.get("result")

        return ExecuteCodeResponse(
            success=True,
            result=result,
            stdout=stdout_capture.getvalue()[:10000],  # Limit stdout
        )
    finally:
        # Clean up HTTP client
        if _http_client is not None:
            await _http_client.aclose()


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
