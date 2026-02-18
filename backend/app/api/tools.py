"""Tool API endpoints.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.schemas.tool import (
    ToolCreate,
    ToolListPaginatedResponse,
    ToolListResponse,
    ToolResponse,
    ToolUpdate,
    ToolVersionCompare,
    ToolVersionListPaginatedResponse,
    ToolVersionListResponse,
    ToolVersionResponse,
    extract_input_schema_from_python,
    validate_python_code,
)
from app.services.sandbox_client import SandboxClient, get_sandbox_client
from app.services.server import ServerService
from app.services.tool import ToolService

router = APIRouter(tags=["tools"])


def get_tool_service(db: AsyncSession = Depends(get_db)) -> ToolService:
    """Dependency to get tool service."""
    return ToolService(db)


def get_server_service(db: AsyncSession = Depends(get_db)) -> ServerService:
    """Dependency to get server service."""
    return ServerService(db)


# Request/Response schemas for code validation endpoint
class CodeValidationRequest(BaseModel):
    """Request schema for Python code validation."""

    code: str = Field(..., max_length=100000, description="Python code to validate")


class CodeValidationResponse(BaseModel):
    """Response schema for Python code validation."""

    valid: bool = Field(..., description="Whether the code is syntactically valid")
    has_main: bool = Field(..., description="Whether the code has an async main() function")
    error: str | None = Field(None, description="Error message if validation failed")
    parameters: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Parameters extracted from main() function signature",
    )
    input_schema: dict[str, Any] | None = Field(
        None,
        description="Generated MCP input schema from main() signature",
    )


class TestCodeRequest(BaseModel):
    """Request schema for testing Python code execution."""

    code: str = Field(..., max_length=100000, description="Python code to test")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments to pass to main() function",
    )
    debug_mode: bool = Field(
        default=False,
        description="Enable debug mode for detailed execution info",
    )


class ErrorDetail(BaseModel):
    """Detailed error information for debugging."""

    message: str = Field(..., description="Error message")
    error_type: str = Field(..., description="Type of error (e.g., ValueError, SyntaxError)")
    line_number: int | None = Field(None, description="Line number where error occurred")
    code_context: list[str] = Field(
        default_factory=list, description="Lines of code around the error"
    )
    traceback: list[str] = Field(default_factory=list, description="Cleaned traceback lines")
    source_file: str = Field(default="<tool>", description="Source file name")


class HttpCallInfo(BaseModel):
    """Information about an HTTP call made during execution."""

    method: str
    url: str
    status_code: int | None = None
    duration_ms: int = 0
    request_headers: dict[str, str] | None = None
    response_preview: str | None = None
    error: str | None = None


class DebugInfo(BaseModel):
    """Debug information captured during execution."""

    http_calls: list[HttpCallInfo] = Field(default_factory=list)
    timing_breakdown: dict[str, int] = Field(default_factory=dict)


class TestCodeResponse(BaseModel):
    """Response schema for Python code test execution."""

    success: bool = Field(..., description="Whether execution succeeded")
    result: Any = Field(default=None, description="Return value from main() function")
    error: str | None = Field(default=None, description="Error message if execution failed")
    error_detail: ErrorDetail | None = Field(
        default=None, description="Detailed error info with line numbers"
    )
    stdout: str | None = Field(default=None, description="Captured stdout output")
    duration_ms: int | None = Field(default=None, description="Execution time in milliseconds")
    debug_info: DebugInfo | None = Field(
        default=None, description="Debug info (when debug_mode=true)"
    )


@router.post(
    "/tools/validate-code",
    response_model=CodeValidationResponse,
    summary="Validate Python code for tool execution",
    description="""
    Validates Python code intended for python_code execution mode.

    Checks:
    - Syntax validity (via AST parsing)
    - Presence of async main() function
    - Extracts parameters from main() signature
    - Generates MCP input schema from type annotations

    This endpoint does NOT execute the code - it only validates structure.
    """,
)
async def validate_code(data: CodeValidationRequest) -> CodeValidationResponse:
    """Validate Python code for tool execution.

    This endpoint validates code without saving it, useful for:
    - Real-time validation in the code editor
    - Checking code before creating/updating a tool
    - Previewing the generated input schema
    """
    result = validate_python_code(data.code)

    # Generate input schema if code is valid and has main()
    input_schema = None
    if result["valid"] and result["has_main"]:
        input_schema = extract_input_schema_from_python(data.code)

    return CodeValidationResponse(
        valid=result["valid"],
        has_main=result["has_main"],
        error=result["error"],
        parameters=result["parameters"],
        input_schema=input_schema,
    )


@router.post(
    "/tools/test-code",
    response_model=TestCodeResponse,
    summary="Test Python code execution in sandbox",
    description="""
    Execute Python code in the sandbox for testing purposes.

    This endpoint:
    - Validates the code first
    - Executes main() with provided arguments
    - Returns result, stdout, and timing information
    - Does NOT save anything to the database

    Use this to test code before creating/updating a tool.
    Note: Code runs without credentials in test mode.
    """,
)
async def test_code(
    data: TestCodeRequest,
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> TestCodeResponse:
    """Test Python code execution in the sandbox.

    Executes the code in a sandboxed environment without saving to database.
    Useful for iterating on code before committing it to a tool.
    """
    # First validate the code
    validation = validate_python_code(data.code)
    if not validation["valid"]:
        return TestCodeResponse(
            success=False,
            error=f"Syntax error: {validation['error']}",
        )
    if not validation["has_main"]:
        return TestCodeResponse(
            success=False,
            error="Code must contain an async main() function",
        )

    # Register a temporary test tool, execute, then clean up
    test_server_id = "__test__"
    test_tool_name = "test_tool"

    try:
        # Register a temporary server with the test tool
        tool_def = {
            "name": test_tool_name,
            "description": "Test execution",
            "parameters": {},
            "python_code": data.code,
            "timeout_ms": 30000,
        }

        reg_result = await sandbox_client.register_server(
            server_id=test_server_id,
            server_name="Test Server",
            tools=[tool_def],
        )

        if not reg_result.get("success"):
            return TestCodeResponse(
                success=False,
                error=f"Failed to register test: {reg_result.get('error')}",
            )

        # Execute the tool
        full_tool_name = f"test_server__{test_tool_name}"
        result = await sandbox_client.call_tool(
            full_tool_name,
            data.arguments,
            debug_mode=data.debug_mode,
        )

        # Build error_detail if present
        error_detail = None
        if result.get("error_detail"):
            ed = result["error_detail"]
            error_detail = ErrorDetail(
                message=ed.get("message", ""),
                error_type=ed.get("error_type", "Error"),
                line_number=ed.get("line_number"),
                code_context=ed.get("code_context", []),
                traceback=ed.get("traceback", []),
                source_file=ed.get("source_file", "<tool>"),
            )

        # Build debug_info if present
        debug_info = None
        if result.get("debug_info"):
            di = result["debug_info"]
            http_calls = [HttpCallInfo(**call) for call in di.get("http_calls", [])]
            debug_info = DebugInfo(
                http_calls=http_calls,
                timing_breakdown=di.get("timing_breakdown", {}),
            )

        return TestCodeResponse(
            success=result.get("success", False),
            result=result.get("result"),
            error=result.get("error"),
            error_detail=error_detail,
            stdout=result.get("stdout"),
            duration_ms=result.get("duration_ms"),
            debug_info=debug_info,
        )

    except Exception as e:
        return TestCodeResponse(
            success=False,
            error=f"Test execution failed: {e!s}",
        )
    finally:
        # Clean up the test server
        await sandbox_client.unregister_server(test_server_id)


@router.post(
    "/servers/{server_id}/tools",
    response_model=ToolResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tool(
    server_id: UUID,
    data: ToolCreate,
    tool_service: ToolService = Depends(get_tool_service),
    server_service: ServerService = Depends(get_server_service),
) -> ToolResponse:
    """Create a new tool for a server.

    Tools use Python code with an async main() function.
    """
    # Verify server exists
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    tool = await tool_service.create(server_id, data)
    return _to_response(tool)


@router.get("/servers/{server_id}/tools", response_model=ToolListPaginatedResponse)
async def list_tools(
    server_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    tool_service: ToolService = Depends(get_tool_service),
    server_service: ServerService = Depends(get_server_service),
) -> ToolListPaginatedResponse:
    """List all tools for a server with pagination."""
    # Verify server exists
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    tools, total = await tool_service.list_by_server(server_id, page=page, page_size=page_size)
    items = [
        ToolListResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            enabled=t.enabled,
            tool_type=t.tool_type,
            external_tool_name=t.external_tool_name,
            approval_status=t.approval_status,
            created_by=t.created_by,
        )
        for t in tools
    ]
    pages = (total + page_size - 1) // page_size if total > 0 else 0
    return ToolListPaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/tools/{tool_id}", response_model=ToolResponse)
async def get_tool(
    tool_id: UUID,
    tool_service: ToolService = Depends(get_tool_service),
) -> ToolResponse:
    """Get a tool by ID."""
    tool = await tool_service.get(tool_id)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_id} not found",
        )
    return _to_response(tool)


@router.patch("/tools/{tool_id}", response_model=ToolResponse)
async def update_tool(
    tool_id: UUID,
    data: ToolUpdate,
    db: AsyncSession = Depends(get_db),
    tool_service: ToolService = Depends(get_tool_service),
    server_service: ServerService = Depends(get_server_service),
) -> ToolResponse:
    """Update a tool.

    If fields that affect the MCP tool definition change (name, description,
    enabled, python_code), re-registers the server with the sandbox and
    notifies MCP clients.
    """
    tool = await tool_service.update(tool_id, data)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_id} not found",
        )

    # Check if any MCP-visible fields changed and server is running
    mcp_fields = {"name", "description", "enabled", "python_code"}
    update_data = data.model_dump(exclude_unset=True)
    if mcp_fields & update_data.keys():
        try:
            server = await server_service.get(tool.server_id)
            if server and server.status == "running":
                from app.api.sandbox import (
                    _build_external_source_configs,
                    _build_tool_definitions,
                )
                from app.services.global_config import GlobalConfigService
                from app.services.server_secret import ServerSecretService

                # Re-register with sandbox
                all_tools, _ = await tool_service.list_by_server(server.id)
                active_tools = [
                    t for t in all_tools if t.enabled and t.approval_status == "approved"
                ]
                tool_defs = _build_tool_definitions(active_tools)

                secret_service = ServerSecretService(db)
                secrets = await secret_service.get_decrypted_for_injection(server.id)
                config_service = GlobalConfigService(db)
                allowed_modules = await config_service.get_allowed_modules()
                external_sources = await _build_external_source_configs(db, server.id, secrets)

                sandbox_client = SandboxClient.get_instance()
                await sandbox_client.register_server(
                    server_id=str(server.id),
                    server_name=server.name,
                    tools=tool_defs,
                    credentials=[],
                    allowed_modules=allowed_modules,
                    secrets=secrets,
                    external_sources=external_sources,
                )

                # Notify MCP clients
                from app.services.tool_change_notifier import fire_and_forget_notify

                fire_and_forget_notify()
        except Exception:
            pass  # Don't fail the update if notification fails

    return _to_response(tool)


@router.delete("/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    tool_id: UUID,
    db: AsyncSession = Depends(get_db),
    tool_service: ToolService = Depends(get_tool_service),
    server_service: ServerService = Depends(get_server_service),
) -> None:
    """Delete a tool.

    If the tool's server is running, notifies MCP clients so they
    refresh their tool list.
    """
    # Fetch tool first to get server_id for notification
    tool = await tool_service.get(tool_id)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_id} not found",
        )

    server_id = tool.server_id
    await tool_service.delete(tool_id)

    # Re-register with sandbox and notify MCP clients if server is running
    try:
        server = await server_service.get(server_id)
        if server and server.status == "running":
            from app.api.sandbox import (
                _build_external_source_configs,
                _build_tool_definitions,
            )
            from app.services.global_config import GlobalConfigService
            from app.services.server_secret import ServerSecretService

            all_tools, _ = await tool_service.list_by_server(server.id)
            active_tools = [t for t in all_tools if t.enabled and t.approval_status == "approved"]
            tool_defs = _build_tool_definitions(active_tools)

            secret_service = ServerSecretService(db)
            secrets = await secret_service.get_decrypted_for_injection(server.id)
            config_service = GlobalConfigService(db)
            allowed_modules = await config_service.get_allowed_modules()
            external_sources = await _build_external_source_configs(db, server.id, secrets)

            sandbox_client = SandboxClient.get_instance()
            await sandbox_client.register_server(
                server_id=str(server.id),
                server_name=server.name,
                tools=tool_defs,
                credentials=[],
                allowed_modules=allowed_modules,
                secrets=secrets,
                external_sources=external_sources,
            )

            from app.services.tool_change_notifier import fire_and_forget_notify

            fire_and_forget_notify()
    except Exception:
        pass  # Don't block delete if notification fails

    return None


def _to_response(tool: Any) -> ToolResponse:
    """Convert tool model to response schema."""
    return ToolResponse(
        id=tool.id,
        server_id=tool.server_id,
        name=tool.name,
        description=tool.description,
        enabled=tool.enabled,
        timeout_ms=tool.timeout_ms,
        python_code=tool.python_code,
        code_dependencies=tool.code_dependencies,
        input_schema=tool.input_schema,
        current_version=tool.current_version,
        tool_type=tool.tool_type,
        external_source_id=tool.external_source_id,
        external_tool_name=tool.external_tool_name,
        approval_status=tool.approval_status,
        approval_requested_at=tool.approval_requested_at,
        approved_at=tool.approved_at,
        approved_by=tool.approved_by,
        rejection_reason=tool.rejection_reason,
        created_by=tool.created_by,
        publish_notes=tool.publish_notes,
        created_at=tool.created_at,
        updated_at=tool.updated_at,
    )


# Version history endpoints


@router.get(
    "/tools/{tool_id}/versions",
    response_model=ToolVersionListPaginatedResponse,
    summary="List tool version history",
)
async def list_tool_versions(
    tool_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    tool_service: ToolService = Depends(get_tool_service),
) -> ToolVersionListPaginatedResponse:
    """List all versions of a tool with pagination, newest first.

    Each version represents a snapshot of the tool's configuration
    at a point in time, with metadata about what changed.
    """
    tool = await tool_service.get(tool_id)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_id} not found",
        )

    versions, total = await tool_service.list_versions(tool_id, page=page, page_size=page_size)
    items = [
        ToolVersionListResponse(
            id=v.id,
            version_number=v.version_number,
            change_summary=v.change_summary,
            change_source=v.change_source,
            created_at=v.created_at,
        )
        for v in versions
    ]
    pages = (total + page_size - 1) // page_size if total > 0 else 0
    return ToolVersionListPaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get(
    "/tools/{tool_id}/versions/compare",
    response_model=ToolVersionCompare,
    summary="Compare two tool versions",
)
async def compare_tool_versions(
    tool_id: UUID,
    from_version: int,
    to_version: int,
    tool_service: ToolService = Depends(get_tool_service),
) -> ToolVersionCompare:
    """Compare two versions of a tool and show the differences.

    Returns a list of fields that changed between versions.
    """
    tool = await tool_service.get(tool_id)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_id} not found",
        )

    v1 = await tool_service.get_version(tool_id, from_version)
    if not v1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {from_version} not found",
        )

    v2 = await tool_service.get_version(tool_id, to_version)
    if not v2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {to_version} not found",
        )

    differences = tool_service.compare_versions(v1, v2)

    return ToolVersionCompare(
        from_version=from_version,
        to_version=to_version,
        differences=differences,
    )


@router.get(
    "/tools/{tool_id}/versions/{version_number}",
    response_model=ToolVersionResponse,
    summary="Get specific tool version",
)
async def get_tool_version(
    tool_id: UUID,
    version_number: int,
    tool_service: ToolService = Depends(get_tool_service),
) -> ToolVersionResponse:
    """Get the full configuration of a specific tool version.

    Use this to view what the tool looked like at a point in history.
    """
    tool = await tool_service.get(tool_id)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_id} not found",
        )

    version = await tool_service.get_version(tool_id, version_number)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} not found for tool {tool_id}",
        )

    return ToolVersionResponse(
        id=version.id,
        tool_id=version.tool_id,
        version_number=version.version_number,
        name=version.name,
        description=version.description,
        enabled=version.enabled,
        timeout_ms=version.timeout_ms,
        python_code=version.python_code,
        input_schema=version.input_schema,
        change_summary=version.change_summary,
        change_source=version.change_source,
        created_at=version.created_at,
    )


@router.post(
    "/tools/{tool_id}/versions/{version_number}/rollback",
    response_model=ToolResponse,
    summary="Rollback tool to a previous version",
)
async def rollback_tool(
    tool_id: UUID,
    version_number: int,
    tool_service: ToolService = Depends(get_tool_service),
) -> ToolResponse:
    """Rollback a tool to a previous version.

    This creates a NEW version with the state from the specified version.
    The tool's version number will increment and the rollback is recorded
    in the version history.
    """
    tool = await tool_service.get(tool_id)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_id} not found",
        )

    if version_number >= tool.current_version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot rollback to current or future version",
        )

    tool = await tool_service.rollback(tool_id, version_number)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} not found",
        )

    return _to_response(tool)
