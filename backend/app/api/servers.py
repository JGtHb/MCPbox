"""Server API endpoints.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.schemas.server import (
    AddHostRequest,
    AllowedHostsResponse,
    ServerCreate,
    ServerListPaginatedResponse,
    ServerListResponse,
    ServerResponse,
    ServerUpdate,
    ToolSummary,
)
from app.services.server import ServerService

logger = logging.getLogger(__name__)

# NOTE: Module configuration is now global - see /api/settings/modules

router = APIRouter(
    prefix="/servers",
    tags=["servers"],
)


def get_server_service(db: AsyncSession = Depends(get_db)) -> ServerService:
    """Dependency to get server service."""
    return ServerService(db)


@router.post("", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    data: ServerCreate,
    service: ServerService = Depends(get_server_service),
) -> ServerResponse:
    """Create a new MCP server."""
    server = await service.create(data)
    return _to_response(server)


@router.get("", response_model=ServerListPaginatedResponse)
async def list_servers(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    service: ServerService = Depends(get_server_service),
) -> ServerListPaginatedResponse:
    """List all MCP servers with pagination."""
    servers, total = await service.list(page=page, page_size=page_size)
    items = [
        ServerListResponse(
            id=s.id,
            name=s.name,
            description=s.description,
            status=s.status,
            network_mode=s.network_mode,
            tool_count=getattr(s, "tool_count", 0),
            created_at=s.created_at,
        )
        for s in servers
    ]
    pages = (total + page_size - 1) // page_size if total > 0 else 0
    return ServerListPaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/{server_id}", response_model=ServerResponse)
async def get_server(
    server_id: UUID,
    service: ServerService = Depends(get_server_service),
) -> ServerResponse:
    """Get a server by ID."""
    server = await service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )
    return _to_response(server)


@router.patch("/{server_id}", response_model=ServerResponse)
async def update_server(
    server_id: UUID,
    data: ServerUpdate,
    service: ServerService = Depends(get_server_service),
) -> ServerResponse:
    """Update a server."""
    server = await service.update(server_id, data)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )
    return _to_response(server)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_id: UUID,
    service: ServerService = Depends(get_server_service),
) -> None:
    """Delete a server and all associated data."""
    deleted = await service.delete(server_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )
    return None


@router.post("/{server_id}/allowed-hosts", response_model=AllowedHostsResponse)
async def add_allowed_host(
    server_id: UUID,
    data: AddHostRequest,
    db: AsyncSession = Depends(get_db),
    service: ServerService = Depends(get_server_service),
) -> AllowedHostsResponse:
    """Add a host to a server's network allowlist.

    Switches network_mode from 'isolated' to 'allowlist' if needed.
    Re-registers the server with the sandbox if it's running.
    """
    server = await service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    # Initialize allowed_hosts if None
    if server.allowed_hosts is None:
        server.allowed_hosts = []

    # Deduplicate
    host = data.host.strip().lower()
    if host not in server.allowed_hosts:
        # Reassign list for PostgreSQL ARRAY dirty tracking
        server.allowed_hosts = [*server.allowed_hosts, host]

    # Switch to allowlist mode if isolated
    if server.network_mode == "isolated":
        server.network_mode = "allowlist"

    await db.commit()
    await db.refresh(server)

    # Re-register with sandbox if running
    await _refresh_server_registration_for_hosts(server, db)

    return AllowedHostsResponse(
        server_id=server.id,
        network_mode=server.network_mode,
        allowed_hosts=server.allowed_hosts or [],
    )


@router.delete("/{server_id}/allowed-hosts", response_model=AllowedHostsResponse)
async def remove_allowed_host(
    server_id: UUID,
    host: str = Query(..., description="Hostname to remove from the allowlist"),
    db: AsyncSession = Depends(get_db),
    service: ServerService = Depends(get_server_service),
) -> AllowedHostsResponse:
    """Remove a host from a server's network allowlist.

    Reverts to 'isolated' mode if the allowlist becomes empty.
    Re-registers the server with the sandbox if it's running.
    """
    server = await service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    host = host.strip().lower()
    current_hosts = server.allowed_hosts or []
    if host not in current_hosts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Host '{host}' is not in the allowlist",
        )

    # Remove host (reassign for PostgreSQL ARRAY dirty tracking)
    server.allowed_hosts = [h for h in current_hosts if h != host]

    # Revert to isolated if empty
    if not server.allowed_hosts:
        server.network_mode = "isolated"

    await db.commit()
    await db.refresh(server)

    # Re-register with sandbox if running
    await _refresh_server_registration_for_hosts(server, db)

    return AllowedHostsResponse(
        server_id=server.id,
        network_mode=server.network_mode,
        allowed_hosts=server.allowed_hosts or [],
    )


async def _refresh_server_registration_for_hosts(server: Any, db: AsyncSession) -> bool:
    """Re-register a server with sandbox after host allowlist change.

    Similar to _refresh_server_registration in approvals.py, but takes a server
    directly instead of a tool with .server relationship.
    """
    if server.status != "running":
        return False

    try:
        from app.api.sandbox import _build_external_source_configs, _build_tool_definitions
        from app.services.global_config import GlobalConfigService
        from app.services.sandbox import SandboxClient
        from app.services.server_secret import ServerSecretService
        from app.services.tool import ToolService

        tool_service = ToolService(db)
        all_tools, _ = await tool_service.list_by_server(server.id)
        active_tools = [t for t in all_tools if t.enabled and t.approval_status == "approved"]
        tool_defs = _build_tool_definitions(active_tools)

        secret_service = ServerSecretService(db)
        secrets = await secret_service.get_decrypted_for_injection(server.id)

        config_service = GlobalConfigService(db)
        allowed_modules = await config_service.get_allowed_modules()

        external_sources_data = await _build_external_source_configs(db, server.id, secrets)

        sandbox_client = SandboxClient.get_instance()
        reg_result = await sandbox_client.register_server(
            server_id=str(server.id),
            server_name=server.name,
            tools=tool_defs,
            allowed_modules=allowed_modules,
            secrets=secrets,
            external_sources=external_sources_data,
        )

        success = bool(reg_result.get("success")) if isinstance(reg_result, dict) else bool(reg_result)
        if success:
            logger.info(f"Server {server.name} re-registered after host allowlist change")
        else:
            logger.warning(f"Failed to re-register server {server.name} after host change")
        return bool(success)

    except Exception as e:
        logger.error(f"Error refreshing server registration for hosts: {e}")
        return False


def _to_response(server: Any) -> ServerResponse:
    """Convert server model to response schema."""
    tools = [
        ToolSummary(
            id=t.id,
            name=t.name,
            description=t.description,
            enabled=t.enabled,
        )
        for t in (server.tools or [])
    ]

    return ServerResponse(
        id=server.id,
        name=server.name,
        description=server.description,
        status=server.status,
        network_mode=server.network_mode,
        default_timeout_ms=server.default_timeout_ms,
        created_at=server.created_at,
        updated_at=server.updated_at,
        tools=tools,
        tool_count=len(tools),
    )


# NOTE: Module configuration endpoints have been removed.
# Module whitelist is now global - see /api/settings/modules
