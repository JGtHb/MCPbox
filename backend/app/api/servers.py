"""Server API endpoints.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.schemas.server import (
    ServerCreate,
    ServerListPaginatedResponse,
    ServerListResponse,
    ServerResponse,
    ServerUpdate,
    ToolSummary,
)
from app.services.server import ServerService

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
        helper_code=server.helper_code,
        created_at=server.created_at,
        updated_at=server.updated_at,
        tools=tools,
        tool_count=len(tools),
        credential_count=len(server.credentials or []),
    )


# NOTE: Module configuration endpoints have been removed.
# Module whitelist is now global - see /api/settings/modules
