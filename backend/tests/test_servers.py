"""Integration tests for server API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_server(async_client: AsyncClient, admin_headers):
    """Test creating a new server."""
    response = await async_client.post(
        "/api/servers",
        json={
            "name": "Test Server",
            "description": "A test server for testing",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Server"
    assert data["description"] == "A test server for testing"
    assert data["status"] == "imported"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_server_duplicate_name(async_client: AsyncClient, admin_headers):
    """Test that creating servers with duplicate names is allowed."""
    # Create first server
    response = await async_client.post(
        "/api/servers",
        json={"name": "Duplicate Server", "description": "First"},
        headers=admin_headers,
    )
    assert response.status_code == 201

    # Create second server with same name - should succeed
    response = await async_client.post(
        "/api/servers",
        json={"name": "Duplicate Server", "description": "Second"},
        headers=admin_headers,
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_create_server_validation(async_client: AsyncClient, admin_headers):
    """Test server creation validation."""
    # Missing name
    response = await async_client.post(
        "/api/servers",
        json={"description": "No name"},
        headers=admin_headers,
    )
    assert response.status_code == 422

    # Empty name
    response = await async_client.post(
        "/api/servers",
        json={"name": "", "description": "Empty name"},
        headers=admin_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_servers(async_client: AsyncClient, admin_headers):
    """Test listing servers with pagination."""
    # Create multiple servers
    for i in range(3):
        await async_client.post(
            "/api/servers",
            json={"name": f"Server {i}", "description": f"Description {i}"},
            headers=admin_headers,
        )

    # List all servers
    response = await async_client.get("/api/servers", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert data["total"] >= 3


@pytest.mark.asyncio
async def test_list_servers_pagination(async_client: AsyncClient, admin_headers):
    """Test server listing pagination."""
    # Create servers
    for i in range(5):
        await async_client.post(
            "/api/servers",
            json={"name": f"Page Server {i}"},
            headers=admin_headers,
        )

    # Get page 1 with small page size
    response = await async_client.get("/api/servers?page=1&page_size=2", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2

    # Get page 2
    response = await async_client.get("/api/servers?page=2&page_size=2", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["page"] == 2


@pytest.mark.asyncio
async def test_get_server(async_client: AsyncClient, admin_headers):
    """Test getting a server by ID."""
    # Create a server
    create_response = await async_client.post(
        "/api/servers",
        json={"name": "Get Test Server"},
        headers=admin_headers,
    )
    server_id = create_response.json()["id"]

    # Get the server
    response = await async_client.get(f"/api/servers/{server_id}", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Get Test Server"
    assert data["id"] == server_id


@pytest.mark.asyncio
async def test_get_server_not_found(async_client: AsyncClient, admin_headers):
    """Test getting a non-existent server."""
    response = await async_client.get(
        "/api/servers/00000000-0000-0000-0000-000000000000", headers=admin_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_server(async_client: AsyncClient, admin_headers):
    """Test updating a server."""
    # Create a server
    create_response = await async_client.post(
        "/api/servers",
        json={"name": "Update Test", "description": "Original"},
        headers=admin_headers,
    )
    server_id = create_response.json()["id"]

    # Update the server
    response = await async_client.patch(
        f"/api/servers/{server_id}",
        json={"description": "Updated description"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["description"] == "Updated description"
    assert data["name"] == "Update Test"  # Name unchanged


@pytest.mark.asyncio
async def test_update_server_name(async_client: AsyncClient, admin_headers):
    """Test updating server name."""
    create_response = await async_client.post(
        "/api/servers",
        json={"name": "Original Name"},
        headers=admin_headers,
    )
    server_id = create_response.json()["id"]

    response = await async_client.patch(
        f"/api/servers/{server_id}",
        json={"name": "New Name"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_update_server_not_found(async_client: AsyncClient, admin_headers):
    """Test updating a non-existent server."""
    response = await async_client.patch(
        "/api/servers/00000000-0000-0000-0000-000000000000",
        json={"name": "New Name"},
        headers=admin_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_server(async_client: AsyncClient, admin_headers):
    """Test deleting a server."""
    # Create a server
    create_response = await async_client.post(
        "/api/servers",
        json={"name": "Delete Test"},
        headers=admin_headers,
    )
    server_id = create_response.json()["id"]

    # Delete the server
    response = await async_client.delete(f"/api/servers/{server_id}", headers=admin_headers)
    assert response.status_code == 204

    # Verify it's deleted
    get_response = await async_client.get(f"/api/servers/{server_id}", headers=admin_headers)
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_server_not_found(async_client: AsyncClient, admin_headers):
    """Test deleting a non-existent server."""
    response = await async_client.delete(
        "/api/servers/00000000-0000-0000-0000-000000000000", headers=admin_headers
    )
    assert response.status_code == 404
