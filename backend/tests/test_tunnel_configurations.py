"""Tests for tunnel configuration management API endpoints."""

import pytest
from httpx import AsyncClient

from app.models import TunnelConfiguration
from app.services.crypto import encrypt_to_base64

pytestmark = pytest.mark.asyncio


@pytest.fixture
def tunnel_config_factory(db_session):
    """Factory for creating test TunnelConfiguration objects."""

    async def _create_config(
        name: str = "Test Config",
        description: str = "A test configuration",
        public_url: str = "https://test.example.com",
        tunnel_token: str = "test-tunnel-token-12345",
        is_active: bool = False,
    ) -> TunnelConfiguration:
        config = TunnelConfiguration(
            name=name,
            description=description,
            public_url=public_url,
            tunnel_token=encrypt_to_base64(tunnel_token, aad="tunnel_token")
            if tunnel_token
            else None,
            is_active=is_active,
        )
        db_session.add(config)
        await db_session.flush()
        await db_session.refresh(config)
        return config

    return _create_config


class TestListConfigurations:
    """Tests for GET /api/tunnel/configurations endpoint."""

    async def test_list_empty(self, async_client: AsyncClient, admin_headers):
        """Test listing configurations when none exist."""
        response = await async_client.get("/api/tunnel/configurations", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    async def test_list_with_configs(
        self, async_client: AsyncClient, tunnel_config_factory, admin_headers
    ):
        """Test listing configurations with multiple configs."""
        await tunnel_config_factory(name="Config 1")
        await tunnel_config_factory(name="Config 2", is_active=True)

        response = await async_client.get("/api/tunnel/configurations", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 2
        # Active config should be first
        assert data["items"][0]["is_active"] is True
        assert data["items"][0]["name"] == "Config 2"

    async def test_list_pagination(
        self, async_client: AsyncClient, tunnel_config_factory, admin_headers
    ):
        """Test pagination."""
        for i in range(5):
            await tunnel_config_factory(name=f"Config {i}")

        response = await async_client.get(
            "/api/tunnel/configurations?page=1&page_size=2", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["pages"] == 3


class TestCreateConfiguration:
    """Tests for POST /api/tunnel/configurations endpoint."""

    async def test_create_configuration(self, async_client: AsyncClient, admin_headers):
        """Test creating a new configuration."""
        response = await async_client.post(
            "/api/tunnel/configurations",
            json={
                "name": "Production",
                "description": "Production tunnel",
                "public_url": "https://mcpbox.example.com",
                "tunnel_token": "eyJhIjoiYmxhaCIsInQiOiJ0b2tlbiJ9",
            },
            headers=admin_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Production"
        assert data["description"] == "Production tunnel"
        assert data["public_url"] == "https://mcpbox.example.com"
        assert data["has_token"] is True
        assert data["is_active"] is False

    async def test_create_without_token_fails(self, async_client: AsyncClient, admin_headers):
        """Test that creating without a token fails."""
        response = await async_client.post(
            "/api/tunnel/configurations",
            json={
                "name": "Test",
            },
            headers=admin_headers,
        )
        assert response.status_code == 422  # Validation error

    async def test_create_normalizes_url(self, async_client: AsyncClient, admin_headers):
        """Test that URL is normalized (adds https://)."""
        response = await async_client.post(
            "/api/tunnel/configurations",
            json={
                "name": "Test",
                "public_url": "mcpbox.example.com/",
                "tunnel_token": "test-token-1234567890",
            },
            headers=admin_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["public_url"] == "https://mcpbox.example.com"


class TestGetConfiguration:
    """Tests for GET /api/tunnel/configurations/{id} endpoint."""

    async def test_get_configuration(
        self, async_client: AsyncClient, tunnel_config_factory, admin_headers
    ):
        """Test getting a configuration by ID."""
        config = await tunnel_config_factory(name="Test Config")

        response = await async_client.get(
            f"/api/tunnel/configurations/{config.id}", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Config"
        assert data["id"] == str(config.id)

    async def test_get_nonexistent_returns_404(self, async_client: AsyncClient, admin_headers):
        """Test getting a nonexistent configuration returns 404."""
        import uuid

        response = await async_client.get(
            f"/api/tunnel/configurations/{uuid.uuid4()}", headers=admin_headers
        )
        assert response.status_code == 404


class TestUpdateConfiguration:
    """Tests for PUT /api/tunnel/configurations/{id} endpoint."""

    async def test_update_configuration(
        self, async_client: AsyncClient, tunnel_config_factory, admin_headers
    ):
        """Test updating a configuration."""
        config = await tunnel_config_factory(name="Original Name")

        response = await async_client.put(
            f"/api/tunnel/configurations/{config.id}",
            json={
                "name": "Updated Name",
                "description": "New description",
            },
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["description"] == "New description"

    async def test_update_token(
        self, async_client: AsyncClient, tunnel_config_factory, admin_headers
    ):
        """Test updating the tunnel token."""
        config = await tunnel_config_factory()

        response = await async_client.put(
            f"/api/tunnel/configurations/{config.id}",
            json={
                "tunnel_token": "new-token-1234567890",
            },
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["has_token"] is True


class TestDeleteConfiguration:
    """Tests for DELETE /api/tunnel/configurations/{id} endpoint."""

    async def test_delete_configuration(
        self, async_client: AsyncClient, tunnel_config_factory, admin_headers
    ):
        """Test deleting a configuration."""
        config = await tunnel_config_factory()

        response = await async_client.delete(
            f"/api/tunnel/configurations/{config.id}", headers=admin_headers
        )
        assert response.status_code == 200

        # Verify it's deleted
        response = await async_client.get(
            f"/api/tunnel/configurations/{config.id}", headers=admin_headers
        )
        assert response.status_code == 404

    async def test_delete_active_fails(
        self, async_client: AsyncClient, tunnel_config_factory, admin_headers
    ):
        """Test that deleting an active configuration fails."""
        config = await tunnel_config_factory(is_active=True)

        response = await async_client.delete(
            f"/api/tunnel/configurations/{config.id}", headers=admin_headers
        )
        assert response.status_code == 400
        assert "active" in response.json()["detail"].lower()


class TestActivateConfiguration:
    """Tests for POST /api/tunnel/configurations/{id}/activate endpoint."""

    async def test_activate_configuration(
        self, async_client: AsyncClient, tunnel_config_factory, admin_headers
    ):
        """Test activating a configuration."""
        config = await tunnel_config_factory()

        response = await async_client.post(
            f"/api/tunnel/configurations/{config.id}/activate", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["configuration"]["is_active"] is True
        assert "Activated" in data["message"]

    async def test_activate_deactivates_others(
        self, async_client: AsyncClient, tunnel_config_factory, admin_headers
    ):
        """Test that activating one config deactivates others."""
        config1 = await tunnel_config_factory(name="Config 1", is_active=True)
        config2 = await tunnel_config_factory(name="Config 2")

        response = await async_client.post(
            f"/api/tunnel/configurations/{config2.id}/activate", headers=admin_headers
        )
        assert response.status_code == 200

        # Check config1 is now inactive
        response = await async_client.get(
            f"/api/tunnel/configurations/{config1.id}", headers=admin_headers
        )
        assert response.json()["is_active"] is False


class TestGetActiveConfiguration:
    """Tests for GET /api/tunnel/configurations/active/current endpoint."""

    async def test_get_active_when_exists(
        self, async_client: AsyncClient, tunnel_config_factory, admin_headers
    ):
        """Test getting the active configuration."""
        await tunnel_config_factory(name="Inactive")
        active = await tunnel_config_factory(name="Active", is_active=True)

        response = await async_client.get(
            "/api/tunnel/configurations/active/current", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Active"
        assert data["id"] == str(active.id)

    async def test_get_active_when_none(self, async_client: AsyncClient, admin_headers):
        """Test getting active configuration when none exists."""
        response = await async_client.get(
            "/api/tunnel/configurations/active/current", headers=admin_headers
        )
        assert response.status_code == 200
        assert response.json() is None
