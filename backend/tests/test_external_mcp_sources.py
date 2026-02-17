"""Integration tests for external MCP sources API endpoints.

Tests the CRUD operations for managing external MCP server connections.
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_mcp_source import ExternalMCPSource

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def test_server(async_client: AsyncClient, admin_headers: dict):
    """Create a test server for external source tests."""
    response = await async_client.post(
        "/api/servers",
        json={"name": "External Sources Test Server"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
async def test_source(
    db_session: AsyncSession, test_server: dict
) -> ExternalMCPSource:
    """Create a test external MCP source directly in the database."""
    source = ExternalMCPSource(
        server_id=test_server["id"],
        name="Test MCP Source",
        url="https://example.com/mcp",
        auth_type="none",
        transport_type="streamable_http",
        status="active",
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.refresh(source)
    return source


class TestCreateExternalSource:
    """Tests for POST /api/external-sources/servers/{server_id}/sources."""

    async def test_create_source(
        self, async_client: AsyncClient, admin_headers: dict, test_server: dict
    ):
        """Create an external MCP source."""
        response = await async_client.post(
            f"/api/external-sources/servers/{test_server['id']}/sources",
            json={
                "name": "GitHub MCP",
                "url": "https://github.com/mcp",
                "auth_type": "none",
                "transport_type": "streamable_http",
            },
            headers=admin_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "GitHub MCP"
        assert data["url"] == "https://github.com/mcp"
        assert data["server_id"] == test_server["id"]
        assert data["status"] == "active"

    async def test_create_source_with_bearer_auth(
        self, async_client: AsyncClient, admin_headers: dict, test_server: dict
    ):
        """Create a source with bearer token auth."""
        response = await async_client.post(
            f"/api/external-sources/servers/{test_server['id']}/sources",
            json={
                "name": "Authenticated MCP",
                "url": "https://api.example.com/mcp",
                "auth_type": "bearer",
                "auth_secret_name": "MCP_API_KEY",
            },
            headers=admin_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["auth_type"] == "bearer"

    async def test_create_source_nonexistent_server(
        self, async_client: AsyncClient, admin_headers: dict
    ):
        """Creating a source for a non-existent server returns 404."""
        response = await async_client.post(
            f"/api/external-sources/servers/{uuid4()}/sources",
            json={
                "name": "Orphan Source",
                "url": "https://example.com/mcp",
            },
            headers=admin_headers,
        )
        assert response.status_code == 404


class TestListExternalSources:
    """Tests for GET /api/external-sources/servers/{server_id}/sources."""

    async def test_list_sources(
        self,
        async_client: AsyncClient,
        admin_headers: dict,
        test_server: dict,
        test_source: ExternalMCPSource,
    ):
        """List external sources for a server."""
        response = await async_client.get(
            f"/api/external-sources/servers/{test_server['id']}/sources",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert any(s["name"] == "Test MCP Source" for s in data)

    async def test_list_sources_empty(
        self, async_client: AsyncClient, admin_headers: dict, test_server: dict
    ):
        """List sources for a server with no sources."""
        response = await async_client.get(
            f"/api/external-sources/servers/{test_server['id']}/sources",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data == []

    async def test_list_sources_nonexistent_server(
        self, async_client: AsyncClient, admin_headers: dict
    ):
        """Listing sources for a non-existent server returns 404."""
        response = await async_client.get(
            f"/api/external-sources/servers/{uuid4()}/sources",
            headers=admin_headers,
        )
        assert response.status_code == 404


class TestGetExternalSource:
    """Tests for GET /api/external-sources/sources/{source_id}."""

    async def test_get_source(
        self,
        async_client: AsyncClient,
        admin_headers: dict,
        test_source: ExternalMCPSource,
    ):
        """Get a specific external source."""
        response = await async_client.get(
            f"/api/external-sources/sources/{test_source.id}",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test MCP Source"
        assert data["url"] == "https://example.com/mcp"

    async def test_get_nonexistent_source(
        self, async_client: AsyncClient, admin_headers: dict
    ):
        """Getting a non-existent source returns 404."""
        response = await async_client.get(
            f"/api/external-sources/sources/{uuid4()}",
            headers=admin_headers,
        )
        assert response.status_code == 404


class TestUpdateExternalSource:
    """Tests for PUT /api/external-sources/sources/{source_id}."""

    async def test_update_source(
        self,
        async_client: AsyncClient,
        admin_headers: dict,
        test_source: ExternalMCPSource,
    ):
        """Update an external source's name and URL."""
        response = await async_client.put(
            f"/api/external-sources/sources/{test_source.id}",
            json={
                "name": "Updated MCP Source",
                "url": "https://new-url.example.com/mcp",
            },
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated MCP Source"
        assert data["url"] == "https://new-url.example.com/mcp"

    async def test_update_nonexistent_source(
        self, async_client: AsyncClient, admin_headers: dict
    ):
        """Updating a non-existent source returns 404."""
        response = await async_client.put(
            f"/api/external-sources/sources/{uuid4()}",
            json={"name": "Ghost Source"},
            headers=admin_headers,
        )
        assert response.status_code == 404


class TestDeleteExternalSource:
    """Tests for DELETE /api/external-sources/sources/{source_id}."""

    async def test_delete_source(
        self,
        async_client: AsyncClient,
        admin_headers: dict,
        test_source: ExternalMCPSource,
    ):
        """Delete an external source."""
        response = await async_client.delete(
            f"/api/external-sources/sources/{test_source.id}",
            headers=admin_headers,
        )
        assert response.status_code == 204

        # Verify it's gone
        response = await async_client.get(
            f"/api/external-sources/sources/{test_source.id}",
            headers=admin_headers,
        )
        assert response.status_code == 404

    async def test_delete_nonexistent_source(
        self, async_client: AsyncClient, admin_headers: dict
    ):
        """Deleting a non-existent source returns 404."""
        response = await async_client.delete(
            f"/api/external-sources/sources/{uuid4()}",
            headers=admin_headers,
        )
        assert response.status_code == 404
