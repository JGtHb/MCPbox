"""Server service - business logic for server management."""

import builtins
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Server, Tool
from app.schemas.server import ServerCreate, ServerUpdate


class ServerService:
    """Service for managing MCP servers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: ServerCreate) -> Server:
        """Create a new server."""
        server = Server(
            name=data.name,
            description=data.description,
            status="imported",
        )
        self.db.add(server)
        await self.db.flush()
        # Re-query with eager loading to get relationships
        result = await self.get(server.id)
        assert result is not None, f"Server {server.id} not found after creation"
        return result

    async def get(self, server_id: UUID) -> Server | None:
        """Get a server by ID with tools and credentials."""
        result = await self.db.execute(
            select(Server)
            .options(
                selectinload(Server.tools),
                selectinload(Server.credentials),
            )
            .where(Server.id == server_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Server | None:
        """Get a server by name."""
        result = await self.db.execute(select(Server).where(Server.name == name))
        return result.scalar_one_or_none()

    async def list(self, page: int = 1, page_size: int = 50) -> tuple[builtins.list[Server], int]:
        """List servers with tool counts and pagination.

        Returns a tuple of (servers, total_count).
        """
        # Get total count first
        count_result = await self.db.execute(select(func.count(Server.id)))
        total = count_result.scalar() or 0

        # Get servers with tool counts, paginated
        # Use secondary sort by id for deterministic ordering when timestamps are identical
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(
                Server,
                func.count(Tool.id).label("tool_count"),
            )
            .outerjoin(Tool)
            .group_by(Server.id)
            .order_by(Server.created_at.desc(), Server.id.desc())
            .offset(offset)
            .limit(page_size)
        )

        servers = []
        for row in result:
            server = row[0]
            server.tool_count = row[1]
            servers.append(server)

        return servers, total

    async def list_with_tools(self) -> builtins.list[Server]:
        """List all servers with their tools eagerly loaded.

        Use this when you need to access server.tools to avoid N+1 queries.
        """
        # Use secondary sort by id for deterministic ordering when timestamps are identical
        result = await self.db.execute(
            select(Server)
            .options(selectinload(Server.tools))
            .order_by(Server.created_at.desc(), Server.id.desc())
        )
        return list(result.scalars().all())

    async def update(self, server_id: UUID, data: ServerUpdate) -> Server | None:
        """Update a server."""
        server = await self.get(server_id)
        if not server:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(server, field, value)

        await self.db.flush()
        await self.db.refresh(server)
        return server

    async def delete(self, server_id: UUID) -> bool:
        """Delete a server and all associated data."""
        server = await self.get(server_id)
        if not server:
            return False

        await self.db.delete(server)
        await self.db.flush()
        return True

    async def update_status(self, server_id: UUID, status: str) -> Server | None:
        """Update server status."""
        server = await self.get(server_id)
        if not server:
            return None

        server.status = status
        await self.db.flush()
        await self.db.refresh(server)
        return server
