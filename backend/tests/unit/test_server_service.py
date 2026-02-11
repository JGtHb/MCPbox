"""Unit tests for ServerService business logic."""

from uuid import uuid4

import pytest

from app.schemas.server import ServerCreate, ServerUpdate
from app.services.server import ServerService

pytestmark = pytest.mark.asyncio


class TestServerServiceCreate:
    """Tests for ServerService.create()."""

    async def test_create_server_basic(self, db_session):
        """Create a basic server."""
        service = ServerService(db_session)

        data = ServerCreate(
            name="test_server",
            description="A test MCP server",
        )

        server = await service.create(data)

        assert server.name == "test_server"
        assert server.description == "A test MCP server"
        assert server.status == "imported"
        assert server.id is not None

    async def test_create_server_minimal(self, db_session):
        """Create a server with minimal data."""
        service = ServerService(db_session)

        data = ServerCreate(name="minimal_server")

        server = await service.create(data)

        assert server.name == "minimal_server"
        assert server.description is None

    async def test_create_server_returns_with_relationships(self, db_session):
        """Created server is returned with eagerly loaded relationships."""
        service = ServerService(db_session)

        data = ServerCreate(name="related_server")

        server = await service.create(data)

        # Should be able to access relationships without additional queries
        assert hasattr(server, "tools")
        assert hasattr(server, "credentials")
        assert server.tools == []
        assert server.credentials == []


class TestServerServiceGet:
    """Tests for ServerService.get()."""

    async def test_get_existing_server(self, db_session, server_factory):
        """Get an existing server by ID."""
        created = await server_factory(name="existing_server")
        service = ServerService(db_session)

        server = await service.get(created.id)

        assert server is not None
        assert server.id == created.id
        assert server.name == "existing_server"

    async def test_get_nonexistent_server(self, db_session):
        """Get non-existent server returns None."""
        service = ServerService(db_session)

        server = await service.get(uuid4())

        assert server is None

    async def test_get_server_loads_relationships(self, db_session, server_factory, tool_factory):
        """Get server eagerly loads tools and credentials."""
        created = await server_factory(name="with_tools")
        await tool_factory(server=created, name="tool1")
        await tool_factory(server=created, name="tool2")

        service = ServerService(db_session)
        server = await service.get(created.id)

        assert len(server.tools) == 2


class TestServerServiceGetByName:
    """Tests for ServerService.get_by_name()."""

    async def test_get_by_name_existing(self, db_session, server_factory):
        """Get existing server by name."""
        await server_factory(name="unique_name")
        service = ServerService(db_session)

        server = await service.get_by_name("unique_name")

        assert server is not None
        assert server.name == "unique_name"

    async def test_get_by_name_nonexistent(self, db_session):
        """Get by non-existent name returns None."""
        service = ServerService(db_session)

        server = await service.get_by_name("does_not_exist")

        assert server is None


class TestServerServiceList:
    """Tests for ServerService.list()."""

    async def test_list_servers_empty(self, db_session):
        """List servers when none exist."""
        service = ServerService(db_session)

        servers, total = await service.list()

        assert servers == []
        assert total == 0

    async def test_list_servers_multiple(self, db_session, server_factory):
        """List multiple servers."""
        await server_factory(name="server1")
        await server_factory(name="server2")
        await server_factory(name="server3")

        service = ServerService(db_session)
        servers, total = await service.list()

        assert total == 3
        assert len(servers) == 3

    async def test_list_servers_pagination(self, db_session, server_factory):
        """List servers respects pagination."""
        for i in range(10):
            await server_factory(name=f"server_{i}")

        service = ServerService(db_session)

        # First page
        servers, total = await service.list(page=1, page_size=3)
        assert total == 10
        assert len(servers) == 3

        # Second page
        servers2, _ = await service.list(page=2, page_size=3)
        assert len(servers2) == 3
        # Should be different servers
        ids_page1 = {s.id for s in servers}
        ids_page2 = {s.id for s in servers2}
        assert ids_page1.isdisjoint(ids_page2)

        # Last page (partial)
        servers4, _ = await service.list(page=4, page_size=3)
        assert len(servers4) == 1

    async def test_list_servers_includes_tool_count(self, db_session, server_factory, tool_factory):
        """List servers includes tool count."""
        server1 = await server_factory(name="server1")
        server2 = await server_factory(name="server2")

        await tool_factory(server=server1, name="tool1")
        await tool_factory(server=server1, name="tool2")
        await tool_factory(server=server2, name="tool3")

        service = ServerService(db_session)
        servers, _ = await service.list()

        # Find the servers by name
        s1 = next(s for s in servers if s.name == "server1")
        s2 = next(s for s in servers if s.name == "server2")

        assert s1.tool_count == 2
        assert s2.tool_count == 1

    async def test_list_servers_ordered_by_created_desc(self, db_session, server_factory):
        """List servers ordered by created_at descending (newest first)."""
        from datetime import datetime, timedelta, timezone

        # Use explicit timestamps to ensure ordering (database server_default won't help
        # when rows are created in quick succession)
        base_time = datetime.now(timezone.utc)
        await server_factory(name="first", created_at=base_time)
        await server_factory(name="second", created_at=base_time + timedelta(seconds=1))
        await server_factory(name="third", created_at=base_time + timedelta(seconds=2))

        service = ServerService(db_session)
        servers, _ = await service.list()

        # Newest first
        assert servers[0].name == "third"
        assert servers[2].name == "first"


class TestServerServiceListWithTools:
    """Tests for ServerService.list_with_tools()."""

    async def test_list_with_tools(self, db_session, server_factory, tool_factory):
        """List servers with tools eagerly loaded."""
        server = await server_factory(name="with_tools")
        await tool_factory(server=server, name="tool1")
        await tool_factory(server=server, name="tool2")

        service = ServerService(db_session)
        servers = await service.list_with_tools()

        assert len(servers) == 1
        assert len(servers[0].tools) == 2

    async def test_list_with_tools_empty(self, db_session):
        """List with tools when no servers exist."""
        service = ServerService(db_session)

        servers = await service.list_with_tools()

        assert servers == []


class TestServerServiceUpdate:
    """Tests for ServerService.update()."""

    async def test_update_name(self, db_session, server_factory):
        """Update server name."""
        server = await server_factory(name="old_name")
        service = ServerService(db_session)

        updated = await service.update(server.id, ServerUpdate(name="new_name"))

        assert updated.name == "new_name"

    async def test_update_description(self, db_session, server_factory):
        """Update server description."""
        server = await server_factory(description="old desc")
        service = ServerService(db_session)

        updated = await service.update(server.id, ServerUpdate(description="new desc"))

        assert updated.description == "new desc"

    async def test_update_multiple_fields(self, db_session, server_factory):
        """Update multiple fields at once."""
        server = await server_factory(name="old", description="old")
        service = ServerService(db_session)

        updated = await service.update(
            server.id,
            ServerUpdate(name="new", description="new"),
        )

        assert updated.name == "new"
        assert updated.description == "new"

    async def test_update_nonexistent_server(self, db_session):
        """Update non-existent server returns None."""
        service = ServerService(db_session)

        result = await service.update(uuid4(), ServerUpdate(name="test"))

        assert result is None

    async def test_update_partial(self, db_session, server_factory):
        """Partial update only changes specified fields."""
        server = await server_factory(name="original", description="original desc")
        service = ServerService(db_session)

        updated = await service.update(
            server.id,
            ServerUpdate(name="changed"),
        )

        assert updated.name == "changed"
        assert updated.description == "original desc"  # Unchanged


class TestServerServiceDelete:
    """Tests for ServerService.delete()."""

    async def test_delete_existing_server(self, db_session, server_factory):
        """Delete an existing server."""
        server = await server_factory()
        server_id = server.id
        service = ServerService(db_session)

        result = await service.delete(server_id)

        assert result is True
        assert await service.get(server_id) is None

    async def test_delete_nonexistent_server(self, db_session):
        """Delete non-existent server returns False."""
        service = ServerService(db_session)

        result = await service.delete(uuid4())

        assert result is False

    async def test_delete_server_cascades_to_tools(self, db_session, server_factory, tool_factory):
        """Deleting server also deletes associated tools."""
        server = await server_factory()
        tool = await tool_factory(server=server)
        tool_id = tool.id
        server_id = server.id

        service = ServerService(db_session)
        await service.delete(server_id)

        # Tool should be deleted too (cascade)
        from sqlalchemy import select

        from app.models import Tool

        result = await db_session.execute(select(Tool).where(Tool.id == tool_id))
        assert result.scalar_one_or_none() is None


class TestServerServiceUpdateStatus:
    """Tests for ServerService.update_status()."""

    async def test_update_status(self, db_session, server_factory):
        """Update server status."""
        server = await server_factory(status="imported")
        service = ServerService(db_session)

        updated = await service.update_status(server.id, "ready")

        assert updated.status == "ready"

    async def test_update_status_nonexistent(self, db_session):
        """Update status of non-existent server returns None."""
        service = ServerService(db_session)

        result = await service.update_status(uuid4(), "ready")

        assert result is None
