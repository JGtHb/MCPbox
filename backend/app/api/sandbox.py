"""Sandbox API endpoints - server lifecycle management.

Uses the shared sandbox service instead of per-server containers.
Accessible without authentication (Option B architecture - admin panel is local-only).
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.services.external_mcp_source import ExternalMCPSourceService
from app.services.global_config import GlobalConfigService
from app.services.sandbox_client import SandboxClient, get_sandbox_client
from app.services.server import ServerService
from app.services.server_secret import ServerSecretService
from app.services.tool import ToolService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


class ServerStatusResponse(BaseModel):
    """Response model for server status."""

    server_id: str
    status: str
    registered_tools: int
    message: str | None = None


class ServerLogsResponse(BaseModel):
    """Response model for server logs."""

    server_id: str
    message: str


def get_server_service(db: AsyncSession = Depends(get_db)) -> ServerService:
    """Dependency to get server service."""
    return ServerService(db)


def get_tool_service(db: AsyncSession = Depends(get_db)) -> ToolService:
    """Dependency to get tool service."""
    return ToolService(db)


def get_global_config_service(db: AsyncSession = Depends(get_db)) -> GlobalConfigService:
    """Dependency to get global config service."""
    return GlobalConfigService(db)


@router.post(
    "/servers/{server_id}/start",
    response_model=ServerStatusResponse,
)
async def start_server(
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    server_service: ServerService = Depends(get_server_service),
    tool_service: ToolService = Depends(get_tool_service),
    global_config_service: GlobalConfigService = Depends(get_global_config_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> ServerStatusResponse:
    """Start a server by registering its tools with the sandbox.

    The server must have tools defined.
    """
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    if server.status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Server is already running",
        )

    # Get tools for this server
    tools, _total = await tool_service.list_by_server(server_id)
    if not tools:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Server has no tools defined. Add tools first.",
        )

    # Build tool definitions for the sandbox
    tool_defs = _build_tool_definitions(tools)

    # Get decrypted secrets for injection
    secret_service = ServerSecretService(db)
    secrets = await secret_service.get_decrypted_for_injection(server_id)

    # Get global allowed modules
    allowed_modules = await global_config_service.get_allowed_modules()

    # Build external MCP source configs for passthrough tools
    external_sources_data = await _build_external_source_configs(db, server_id, secrets)

    # Determine allowed hosts for network access enforcement
    allowed_hosts = server.allowed_hosts if server.network_mode == "allowlist" else None

    try:
        # Register with sandbox (include helper_code, allowed_modules, and network config)
        result = await sandbox_client.register_server(
            server_id=str(server_id),
            server_name=server.name,
            tools=tool_defs,
            credentials=[],
            helper_code=server.helper_code,
            allowed_modules=allowed_modules,
            secrets=secrets,
            external_sources=external_sources_data,
            allowed_hosts=allowed_hosts,
        )

        if not result.get("success"):
            logger.error(f"Failed to register server with sandbox: {result.get('error')}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to register server with sandbox. Check sandbox service status.",
            )

        # Update server status
        await server_service.update_status(server_id, "running")
        await db.commit()

        # Notify MCP clients that tool list has changed
        from app.services.tool_change_notifier import fire_and_forget_notify

        fire_and_forget_notify()

        return ServerStatusResponse(
            server_id=str(server_id),
            status="running",
            registered_tools=result.get("tools_registered", len(tool_defs)),
            message="Server started successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to start server {server_id}: {e}")
        await server_service.update_status(server_id, "error")
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start server due to an internal error",
        ) from e


@router.post(
    "/servers/{server_id}/stop",
    response_model=ServerStatusResponse,
)
async def stop_server(
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    server_service: ServerService = Depends(get_server_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> ServerStatusResponse:
    """Stop a server by unregistering its tools from the sandbox."""
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    if server.status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Server is not running",
        )

    try:
        # Unregister from sandbox
        await sandbox_client.unregister_server(str(server_id))

        # Update server status (even if not found in sandbox)
        await server_service.update_status(server_id, "stopped")
        await db.commit()

        # Notify MCP clients that tool list has changed
        from app.services.tool_change_notifier import fire_and_forget_notify

        fire_and_forget_notify()

        return ServerStatusResponse(
            server_id=str(server_id),
            status="stopped",
            registered_tools=0,
            message="Server stopped successfully",
        )

    except Exception as e:
        logger.exception(f"Failed to stop server {server_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to stop server due to an internal error",
        ) from e


@router.post(
    "/servers/{server_id}/restart",
    response_model=ServerStatusResponse,
)
async def restart_server(
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    server_service: ServerService = Depends(get_server_service),
    tool_service: ToolService = Depends(get_tool_service),
    global_config_service: GlobalConfigService = Depends(get_global_config_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> ServerStatusResponse:
    """Restart a server by re-registering its tools."""
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    # Unregister first (ignore errors)
    await sandbox_client.unregister_server(str(server_id))

    # Get tools
    tools, _total = await tool_service.list_by_server(server_id)
    if not tools:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Server has no tools defined.",
        )

    # Build tool definitions
    tool_defs = _build_tool_definitions(tools)

    # Get decrypted secrets for injection
    secret_service = ServerSecretService(db)
    secrets = await secret_service.get_decrypted_for_injection(server_id)

    # Get global allowed modules
    allowed_modules = await global_config_service.get_allowed_modules()

    # Build external MCP source configs for passthrough tools
    external_sources_data = await _build_external_source_configs(db, server_id, secrets)

    # Determine allowed hosts for network access enforcement
    allowed_hosts = server.allowed_hosts if server.network_mode == "allowlist" else None

    try:
        # Re-register (include helper_code, allowed_modules, and network config)
        result = await sandbox_client.register_server(
            server_id=str(server_id),
            server_name=server.name,
            tools=tool_defs,
            credentials=[],
            helper_code=server.helper_code,
            allowed_modules=allowed_modules,
            secrets=secrets,
            external_sources=external_sources_data,
            allowed_hosts=allowed_hosts,
        )

        if not result.get("success"):
            logger.error(f"Failed to re-register server with sandbox: {result.get('error')}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to register server with sandbox. Check sandbox service status.",
            )

        await server_service.update_status(server_id, "running")
        await db.commit()

        return ServerStatusResponse(
            server_id=str(server_id),
            status="running",
            registered_tools=result.get("tools_registered", len(tool_defs)),
            message="Server restarted successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to restart server {server_id}: {e}")
        await server_service.update_status(server_id, "error")
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to restart server due to an internal error",
        ) from e


@router.get(
    "/servers/{server_id}/status",
    response_model=ServerStatusResponse,
)
async def get_server_status(
    server_id: UUID,
    server_service: ServerService = Depends(get_server_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> ServerStatusResponse:
    """Get current status of a server."""
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    # Check if registered in sandbox
    tools = await sandbox_client.list_tools(str(server_id))

    return ServerStatusResponse(
        server_id=str(server_id),
        status=server.status,
        registered_tools=len(tools),
    )


@router.get(
    "/servers/{server_id}/logs",
    response_model=ServerLogsResponse,
)
async def get_server_logs(
    server_id: UUID,
    server_service: ServerService = Depends(get_server_service),
) -> ServerLogsResponse:
    """Get logs for a server.

    Note: With the shared sandbox architecture, per-server logs
    are available through the Activity page instead.
    """
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    return ServerLogsResponse(
        server_id=str(server_id),
        message="Per-server logs are available in the Activity dashboard. Filter by server_id.",
    )


def _build_tool_definitions(tools: list) -> list[dict]:
    """Build tool definitions for sandbox registration (all tools, no filtering)."""
    from app.services.tool_utils import build_tool_definitions

    return build_tool_definitions(tools)


async def _build_external_source_configs(
    db: AsyncSession,
    server_id: UUID,
    secrets: dict[str, str],
) -> list[dict]:
    """Build external MCP source configs for sandbox registration.

    Resolves auth credentials from server secrets and builds the config
    dicts that the sandbox needs to connect to external MCP servers.
    """
    source_service = ExternalMCPSourceService(db)
    sources = await source_service.list_by_server(server_id)

    configs = []
    for source in sources:
        if source.status == "disabled":
            continue

        auth_headers = await source_service._build_auth_headers(source, secrets)

        configs.append(
            {
                "source_id": str(source.id),
                "url": source.url,
                "auth_headers": auth_headers,
                "transport_type": source.transport_type,
            }
        )

    return configs
