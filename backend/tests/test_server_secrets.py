"""Integration tests for server secrets API endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

NONEXISTENT_SERVER_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
async def test_server(async_client, admin_headers):
    response = await async_client.post(
        "/api/servers",
        json={"name": "Secrets Test Server"},
        headers=admin_headers,
    )
    return response.json()


async def test_create_secret(async_client: AsyncClient, test_server, admin_headers):
    """Test creating a secret placeholder and verifying the response."""
    server_id = test_server["id"]
    response = await async_client.post(
        f"/api/servers/{server_id}/secrets",
        json={"key_name": "API_KEY", "description": "Test API key"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["key_name"] == "API_KEY"
    assert data["description"] == "Test API key"
    assert data["has_value"] is False
    assert data["server_id"] == server_id
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


async def test_list_secrets(async_client: AsyncClient, test_server, admin_headers):
    """Test listing secrets after creating multiple."""
    server_id = test_server["id"]

    # Create multiple secrets
    for key in ("SECRET_A", "SECRET_B", "SECRET_C"):
        resp = await async_client.post(
            f"/api/servers/{server_id}/secrets",
            json={"key_name": key},
            headers=admin_headers,
        )
        assert resp.status_code == 201

    # List secrets
    response = await async_client.get(
        f"/api/servers/{server_id}/secrets",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == 3
    assert len(data["items"]) == 3

    key_names = [item["key_name"] for item in data["items"]]
    assert "SECRET_A" in key_names
    assert "SECRET_B" in key_names
    assert "SECRET_C" in key_names


async def test_set_secret_value(async_client: AsyncClient, test_server, admin_headers):
    """Test setting a secret value and verifying has_value becomes true."""
    server_id = test_server["id"]

    # Create a secret placeholder
    create_resp = await async_client.post(
        f"/api/servers/{server_id}/secrets",
        json={"key_name": "MY_TOKEN"},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["has_value"] is False

    # Set the value
    response = await async_client.put(
        f"/api/servers/{server_id}/secrets/MY_TOKEN",
        json={"value": "the-secret-value"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["has_value"] is True
    assert data["key_name"] == "MY_TOKEN"


async def test_secret_value_not_in_response(
    async_client: AsyncClient, test_server, admin_headers
):
    """Test that the actual secret value never appears in any API response."""
    server_id = test_server["id"]
    secret_value = "super-secret-do-not-leak"

    # Create and set value
    await async_client.post(
        f"/api/servers/{server_id}/secrets",
        json={"key_name": "LEAK_CHECK"},
        headers=admin_headers,
    )
    put_resp = await async_client.put(
        f"/api/servers/{server_id}/secrets/LEAK_CHECK",
        json={"value": secret_value},
        headers=admin_headers,
    )
    assert put_resp.status_code == 200
    put_data = put_resp.json()

    # Value must not appear in the PUT response
    assert "value" not in put_data
    assert secret_value not in str(put_data)

    # Value must not appear in the list response
    list_resp = await async_client.get(
        f"/api/servers/{server_id}/secrets",
        headers=admin_headers,
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert secret_value not in str(list_data)
    for item in list_data["items"]:
        assert "value" not in item


async def test_delete_secret(async_client: AsyncClient, test_server, admin_headers):
    """Test deleting a secret and verifying it is gone."""
    server_id = test_server["id"]

    # Create a secret
    await async_client.post(
        f"/api/servers/{server_id}/secrets",
        json={"key_name": "TEMP_KEY"},
        headers=admin_headers,
    )

    # Delete it
    response = await async_client.delete(
        f"/api/servers/{server_id}/secrets/TEMP_KEY",
        headers=admin_headers,
    )
    assert response.status_code == 204

    # Verify it is gone by listing
    list_resp = await async_client.get(
        f"/api/servers/{server_id}/secrets",
        headers=admin_headers,
    )
    assert list_resp.status_code == 200
    key_names = [item["key_name"] for item in list_resp.json()["items"]]
    assert "TEMP_KEY" not in key_names


async def test_create_secret_nonexistent_server(
    async_client: AsyncClient, admin_headers
):
    """Test that creating a secret for a nonexistent server returns 404."""
    response = await async_client.post(
        f"/api/servers/{NONEXISTENT_SERVER_ID}/secrets",
        json={"key_name": "API_KEY"},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_create_duplicate_key(async_client: AsyncClient, test_server, admin_headers):
    """Test that creating a secret with a duplicate key_name returns 409."""
    server_id = test_server["id"]

    # Create the first secret
    resp = await async_client.post(
        f"/api/servers/{server_id}/secrets",
        json={"key_name": "DUPLICATE_KEY"},
        headers=admin_headers,
    )
    assert resp.status_code == 201

    # Try to create another secret with the same key_name
    response = await async_client.post(
        f"/api/servers/{server_id}/secrets",
        json={"key_name": "DUPLICATE_KEY"},
        headers=admin_headers,
    )
    assert response.status_code == 409


async def test_set_value_nonexistent_secret(
    async_client: AsyncClient, test_server, admin_headers
):
    """Test that setting a value on a nonexistent secret returns 404."""
    server_id = test_server["id"]
    response = await async_client.put(
        f"/api/servers/{server_id}/secrets/DOES_NOT_EXIST",
        json={"value": "some-value"},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_delete_nonexistent_secret(
    async_client: AsyncClient, test_server, admin_headers
):
    """Test that deleting a nonexistent secret returns 404."""
    server_id = test_server["id"]
    response = await async_client.delete(
        f"/api/servers/{server_id}/secrets/DOES_NOT_EXIST",
        headers=admin_headers,
    )
    assert response.status_code == 404
