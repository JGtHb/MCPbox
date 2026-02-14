"""Integration tests for credential API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.fixture
async def test_server(async_client: AsyncClient, admin_headers):
    """Create a test server for credential tests."""
    response = await async_client.post(
        "/api/servers",
        json={"name": "Credential Test Server"},
        headers=admin_headers,
    )
    return response.json()


@pytest.mark.asyncio
async def test_create_credential_api_key_header(
    async_client: AsyncClient, test_server, admin_headers
):
    """Test creating an API key header credential."""
    response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "MY_API_KEY",
            "description": "Test API key",
            "auth_type": "api_key_header",
            "header_name": "X-API-Key",
            "value": "secret-key-12345",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "MY_API_KEY"
    assert data["auth_type"] == "api_key_header"
    assert data["header_name"] == "X-API-Key"
    assert data["has_value"] is True
    # Value should not be returned for security
    assert "value" not in data or data.get("value") is None


@pytest.mark.asyncio
async def test_create_credential_bearer(
    async_client: AsyncClient, test_server, admin_headers
):
    """Test creating a bearer token credential."""
    response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "AUTH_TOKEN",
            "auth_type": "bearer",
            "value": "bearer-token-secret",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["auth_type"] == "bearer"
    assert data["has_value"] is True


@pytest.mark.asyncio
async def test_create_credential_basic_auth(
    async_client: AsyncClient, test_server, admin_headers
):
    """Test creating a basic auth credential."""
    response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "BASIC_AUTH",
            "auth_type": "basic",
            "username": "testuser",
            "password": "testpass",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["auth_type"] == "basic"
    assert data["has_username"] is True
    assert data["has_password"] is True


@pytest.mark.asyncio
async def test_create_credential_validation(
    async_client: AsyncClient, test_server, admin_headers
):
    """Test credential creation validation."""
    # Missing header_name for api_key_header
    response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "INVALID",
            "auth_type": "api_key_header",
            "value": "some-value",
            # Missing header_name
        },
        headers=admin_headers,
    )
    assert response.status_code == 422

    # Missing username for basic auth
    response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "INVALID",
            "auth_type": "basic",
            "password": "only-password",
        },
        headers=admin_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_credentials(async_client: AsyncClient, test_server, admin_headers):
    """Test listing credentials with pagination."""
    # Create multiple credentials
    for i in range(3):
        await async_client.post(
            f"/api/servers/{test_server['id']}/credentials",
            json={
                "name": f"CRED_{i}",
                "auth_type": "bearer",
                "value": f"token-{i}",
            },
            headers=admin_headers,
        )

    # List credentials
    response = await async_client.get(
        f"/api/servers/{test_server['id']}/credentials", headers=admin_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 3


@pytest.mark.asyncio
async def test_list_credentials_server_not_found(
    async_client: AsyncClient, admin_headers
):
    """Test listing credentials for non-existent server."""
    response = await async_client.get(
        "/api/servers/00000000-0000-0000-0000-000000000000/credentials",
        headers=admin_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_credential(async_client: AsyncClient, test_server, admin_headers):
    """Test getting a credential by ID."""
    # Create a credential
    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "GET_TEST",
            "auth_type": "bearer",
            "value": "secret",
        },
        headers=admin_headers,
    )
    credential_id = create_response.json()["id"]

    # Get the credential
    response = await async_client.get(
        f"/api/credentials/{credential_id}", headers=admin_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "GET_TEST"
    assert data["has_value"] is True


@pytest.mark.asyncio
async def test_get_credential_not_found(async_client: AsyncClient, admin_headers):
    """Test getting a non-existent credential."""
    response = await async_client.get(
        "/api/credentials/00000000-0000-0000-0000-000000000000", headers=admin_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_credential(async_client: AsyncClient, test_server, admin_headers):
    """Test updating a credential."""
    # Create a credential
    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "UPDATE_TEST",
            "description": "Original",
            "auth_type": "bearer",
            "value": "old-value",
        },
        headers=admin_headers,
    )
    credential_id = create_response.json()["id"]

    # Update the credential
    response = await async_client.patch(
        f"/api/credentials/{credential_id}",
        json={
            "description": "Updated",
            "value": "new-value",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["description"] == "Updated"
    assert data["has_value"] is True


@pytest.mark.asyncio
async def test_update_credential_name(
    async_client: AsyncClient, test_server, admin_headers
):
    """Test updating credential name."""
    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "OLD_NAME",
            "auth_type": "bearer",
            "value": "token",
        },
        headers=admin_headers,
    )
    credential_id = create_response.json()["id"]

    response = await async_client.patch(
        f"/api/credentials/{credential_id}",
        json={"name": "NEW_NAME"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "NEW_NAME"


@pytest.mark.asyncio
async def test_delete_credential(async_client: AsyncClient, test_server, admin_headers):
    """Test deleting a credential."""
    # Create a credential
    create_response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "DELETE_TEST",
            "auth_type": "bearer",
            "value": "token",
        },
        headers=admin_headers,
    )
    credential_id = create_response.json()["id"]

    # Delete the credential
    response = await async_client.delete(
        f"/api/credentials/{credential_id}", headers=admin_headers
    )
    assert response.status_code == 204

    # Verify it's deleted
    get_response = await async_client.get(
        f"/api/credentials/{credential_id}", headers=admin_headers
    )
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_credential_not_found(async_client: AsyncClient, admin_headers):
    """Test deleting a non-existent credential."""
    response = await async_client.delete(
        "/api/credentials/00000000-0000-0000-0000-000000000000", headers=admin_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_credential_cascade_delete(
    async_client: AsyncClient, test_server, admin_headers
):
    """Test that credentials are deleted when server is deleted."""
    # Create a credential
    cred_response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "CASCADE_TEST",
            "auth_type": "bearer",
            "value": "token",
        },
        headers=admin_headers,
    )
    credential_id = cred_response.json()["id"]

    # Delete the server
    await async_client.delete(
        f"/api/servers/{test_server['id']}", headers=admin_headers
    )

    # Credential should also be deleted
    get_response = await async_client.get(
        f"/api/credentials/{credential_id}", headers=admin_headers
    )
    assert get_response.status_code == 404
