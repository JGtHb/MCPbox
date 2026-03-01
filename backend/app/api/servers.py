"""Server API endpoints.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sandbox import reregister_server
from app.core import get_db
from app.models.network_access_request import NetworkAccessRequest
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
from app.services.approval import sync_allowed_hosts
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
            allowed_hosts=s.allowed_hosts or [],
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

    Creates an auto-approved NetworkAccessRequest record, then syncs the cache.
    Re-registers the server with the sandbox if it's running.
    """
    server = await service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    host = data.host.strip().lower()

    # Deduplicate: skip if an approved admin record already exists for this host+server
    existing = await db.execute(
        select(NetworkAccessRequest).where(
            NetworkAccessRequest.server_id == server.id,
            NetworkAccessRequest.tool_id.is_(None),
            NetworkAccessRequest.host == host,
            NetworkAccessRequest.status == "approved",
        )
    )
    if not existing.scalar_one_or_none():
        now = datetime.now(UTC)
        record = NetworkAccessRequest(
            server_id=server.id,
            tool_id=None,
            host=host,
            port=None,
            justification="Manually added by admin",
            requested_by="admin",
            status="approved",
            reviewed_at=now,
            reviewed_by="admin",
        )
        db.add(record)

    # Sync cache from records
    await sync_allowed_hosts(server.id, db)
    await db.commit()
    await db.refresh(server)

    # Re-register with sandbox if running
    await reregister_server(server.id, db)

    return AllowedHostsResponse(
        server_id=server.id,
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

    Deletes the admin-originated record, then syncs the cache.
    Re-registers the server with the sandbox if it's running.
    """
    server = await service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    host = host.strip().lower()
    if host not in (server.allowed_hosts or []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Host '{host}' is not in the allowlist",
        )

    # Delete admin-originated record (tool_id IS NULL) for this host+server.
    # LLM-originated records are preserved for audit history.
    result = await db.execute(
        select(NetworkAccessRequest).where(
            NetworkAccessRequest.server_id == server.id,
            NetworkAccessRequest.tool_id.is_(None),
            NetworkAccessRequest.host == host,
            NetworkAccessRequest.status == "approved",
        )
    )
    admin_record = result.scalar_one_or_none()
    if admin_record:
        await db.delete(admin_record)

    # Sync cache from records
    await sync_allowed_hosts(server.id, db)
    await db.commit()
    await db.refresh(server)

    # Re-register with sandbox if running
    await reregister_server(server.id, db)

    return AllowedHostsResponse(
        server_id=server.id,
        allowed_hosts=server.allowed_hosts or [],
    )


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
        allowed_hosts=server.allowed_hosts or [],
        default_timeout_ms=server.default_timeout_ms,
        created_at=server.created_at,
        updated_at=server.updated_at,
        tools=tools,
        tool_count=len(tools),
    )


# NOTE: Module configuration endpoints have been removed.
# Module whitelist is now global - see /api/settings/modules
