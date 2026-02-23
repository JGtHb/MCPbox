"""Tool API endpoints.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.models import Tool
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
from app.services.execution_log import ExecutionLogService
from app.services.global_config import GlobalConfigService
from app.services.sandbox_client import SandboxClient, get_sandbox_client
from app.services.server import ServerService
from app.services.server_secret import ServerSecretService
from app.services.setting import SettingService
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
    """Request schema for testing a saved tool's code execution."""

    tool_id: UUID = Field(..., description="UUID of the tool to test")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments to pass to main() function",
    )


class TestCodeResponse(BaseModel):
    """Response schema for tool test execution."""

    success: bool = Field(..., description="Whether execution succeeded")
    result: Any = Field(default=None, description="Return value from main() function")
    error: str | None = Field(default=None, description="Error message if execution failed")
    stdout: str | None = Field(default=None, description="Captured stdout output")
    duration_ms: int | None = Field(default=None, description="Execution time in milliseconds")


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
    summary="Test a saved tool's code in the sandbox",
    description="""
    Execute a saved tool's code in the sandbox for testing purposes.

    This endpoint:
    - Requires an existing tool_id (tool must be saved first)
    - Enforces the approval gate (blocks testing of unapproved tools when require_approval mode is active)
    - Runs the tool's actual code with its real server secrets and network config
    - Logs the test run in the tool's execution history (labeled as a test)
    - Returns result, stdout, and timing information
    """,
)
async def test_code(
    data: TestCodeRequest,
    db: AsyncSession = Depends(get_db),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> TestCodeResponse:
    """Test a saved tool's code in the sandbox.

    Fetches the tool from the database and runs it with the same environment
    (secrets, network allowlist, approved modules) as production execution.
    """
    # Fetch the tool
    tool_result = await db.execute(select(Tool).where(Tool.id == data.tool_id))
    tool = tool_result.scalar_one_or_none()
    if not tool:
        return TestCodeResponse(
            success=False,
            error=f"Tool {data.tool_id} not found",
        )

    if not tool.python_code:
        return TestCodeResponse(
            success=False,
            error="Tool has no code to test",
        )

    # Enforce admin approval gate
    setting_service = SettingService(db)
    approval_mode = await setting_service.get_value(
        "tool_approval_mode", default="require_approval"
    )
    if approval_mode == "require_approval" and tool.approval_status != "approved":
        return TestCodeResponse(
            success=False,
            error=(
                f"Tool '{tool.name}' cannot be tested until it is approved "
                f"(current status: {tool.approval_status}). "
                "Submit it for review or ask the admin to set tool_approval_mode to 'auto_approve'."
            ),
        )

    # Fetch live admin-approved modules and server context
    config_service = GlobalConfigService(db)
    allowed_modules = await config_service.get_allowed_modules()

    server_service = ServerService(db)
    server = await server_service.get(tool.server_id)
    secret_service = ServerSecretService(db)
    secrets = await secret_service.get_decrypted_for_injection(tool.server_id)
    allowed_hosts = (server.allowed_hosts or []) if server else []

    start_ms = time.monotonic()
    try:
        result = await sandbox_client.execute_code(
            code=tool.python_code,
            arguments=data.arguments,
            timeout_seconds=30,
            secrets=secrets,
            allowed_hosts=allowed_hosts,
            allowed_modules=allowed_modules,
        )
    except Exception as e:
        return TestCodeResponse(
            success=False,
            error=f"Test execution failed: {e!s}",
        )

    duration_ms = int((time.monotonic() - start_ms) * 1000)

    # Log the test run — same table as production, just flagged is_test=True
    try:
        log_service = ExecutionLogService(db)
        await log_service.create_log(
            tool_id=tool.id,
            server_id=tool.server_id,
            tool_name=tool.name,
            input_args={"arguments": data.arguments},
            result=result.get("result"),
            error=result.get("error"),
            stdout=result.get("stdout"),
            duration_ms=duration_ms,
            success=result.get("success", False),
            is_test=True,
        )
        await db.commit()
    except Exception:
        pass  # Never fail the test run due to logging errors

    return TestCodeResponse(
        success=result.get("success", False),
        result=result.get("result"),
        error=result.get("error"),
        stdout=result.get("stdout"),
        duration_ms=result.get("duration_ms"),
    )


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
                    allowed_modules=allowed_modules,
                    secrets=secrets,
                    external_sources=external_sources,
                    allowed_hosts=server.allowed_hosts or [],
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
                allowed_modules=allowed_modules,
                secrets=secrets,
                external_sources=external_sources,
                allowed_hosts=server.allowed_hosts or [],
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
