"""Tests for tunnel API endpoints (start, stop, status).

Tests the orchestration layer of tunnel management at the API level.
Service-level tests are in test_tunnel_service.py.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.main import app
from app.models import TunnelConfiguration
from app.services.audit import get_audit_service
from app.services.crypto import encrypt_to_base64
from app.services.tunnel import TunnelService, get_tunnel_service

pytestmark = pytest.mark.asyncio


@contextmanager
def override_tunnel_service(mock_service):
    """Context manager to override tunnel service dependency."""
    app.dependency_overrides[get_tunnel_service] = lambda: mock_service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_tunnel_service, None)


@contextmanager
def override_audit_service(mock_audit):
    """Context manager to override audit service dependency."""
    app.dependency_overrides[get_audit_service] = lambda: mock_audit
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_audit_service, None)


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
            tunnel_token=encrypt_to_base64(tunnel_token) if tunnel_token else None,
            is_active=is_active,
        )
        db_session.add(config)
        await db_session.flush()
        await db_session.refresh(config)
        return config

    return _create_config


@pytest.fixture
def reset_tunnel_service():
    """Reset TunnelService singleton state before and after each test."""
    # Save original state
    original_instance = TunnelService._instance

    # Reset for test
    TunnelService._instance = None
    TunnelService._process = None
    TunnelService._url = None
    TunnelService._status = "disconnected"
    TunnelService._error = None
    TunnelService._started_at = None
    TunnelService._status_callbacks = []
    TunnelService._named_tunnel_url = None
    TunnelService._lock = None

    yield

    # Restore original state
    TunnelService._instance = original_instance


class TestTunnelStatus:
    """Tests for GET /api/tunnel/status endpoint."""

    async def test_status_returns_disconnected_initially(
        self, async_client: AsyncClient, reset_tunnel_service, admin_headers
    ):
        """Test that status returns disconnected when no tunnel is running."""
        with patch.object(TunnelService, "health_check", new_callable=AsyncMock):
            response = await async_client.get("/api/tunnel/status", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disconnected"
        assert data["url"] is None
        assert data["error"] is None

    async def test_status_returns_connected_when_running(
        self, async_client: AsyncClient, reset_tunnel_service, admin_headers
    ):
        """Test that status returns connected when tunnel is running."""
        # Set up mock tunnel service with connected state
        mock_service = MagicMock()
        mock_service.status = "connected"
        mock_service.get_effective_status = AsyncMock(
            return_value={
                "status": "connected",
                "url": "https://test.cloudflare.com",
                "started_at": "2025-01-01T00:00:00Z",
                "error": None,
            }
        )
        mock_service.health_check = AsyncMock()

        with override_tunnel_service(mock_service):
            response = await async_client.get("/api/tunnel/status", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["url"] == "https://test.cloudflare.com"

    async def test_status_returns_error_state(
        self, async_client: AsyncClient, reset_tunnel_service, admin_headers
    ):
        """Test that status returns error details when tunnel has errors."""
        mock_service = MagicMock()
        mock_service.status = "error"
        mock_service.get_effective_status = AsyncMock(
            return_value={
                "status": "error",
                "url": None,
                "started_at": None,
                "error": "Connection refused",
            }
        )
        mock_service.health_check = AsyncMock()

        with override_tunnel_service(mock_service):
            response = await async_client.get("/api/tunnel/status", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["error"] == "Connection refused"


class TestTunnelStart:
    """Tests for POST /api/tunnel/start endpoint."""

    async def test_start_without_active_config_fails(
        self, async_client: AsyncClient, reset_tunnel_service, admin_headers
    ):
        """Test that starting tunnel without active configuration fails."""
        response = await async_client.post("/api/tunnel/start", headers=admin_headers)

        assert response.status_code == 400
        data = response.json()
        assert "No active tunnel configuration" in data["detail"]

    async def test_start_with_active_config_succeeds(
        self,
        async_client: AsyncClient,
        tunnel_config_factory,
        reset_tunnel_service,
        admin_headers,
    ):
        """Test that starting tunnel with active configuration succeeds."""
        # Create an active configuration
        await tunnel_config_factory(
            name="Production",
            public_url="https://mcpbox.example.com",
            tunnel_token="eyJhIjoiYmxhaCIsInQiOiJ0b2tlbiJ9",
            is_active=True,
        )

        # Mock the tunnel service start
        mock_service = MagicMock()
        mock_service.start = AsyncMock(
            return_value={
                "status": "connected",
                "url": "https://mcpbox.example.com",
                "started_at": "2025-01-01T00:00:00Z",
            }
        )

        with override_tunnel_service(mock_service):
            response = await async_client.post("/api/tunnel/start", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["url"] == "https://mcpbox.example.com"

        # Verify start was called with correct token
        mock_service.start.assert_called_once()
        call_kwargs = mock_service.start.call_args[1]
        assert call_kwargs["named_tunnel_url"] == "https://mcpbox.example.com"
        assert "tunnel_token" in call_kwargs

    async def test_start_with_missing_token_fails(
        self,
        async_client: AsyncClient,
        db_session,
        reset_tunnel_service,
        admin_headers,
    ):
        """Test that starting tunnel with missing token fails."""
        # Create config without token (direct DB insert to bypass validation)
        config = TunnelConfiguration(
            name="No Token Config",
            public_url="https://test.example.com",
            tunnel_token=None,
            is_active=True,
        )
        db_session.add(config)
        await db_session.flush()

        response = await async_client.post("/api/tunnel/start", headers=admin_headers)

        assert response.status_code == 400
        data = response.json()
        assert "missing tunnel token" in data["detail"].lower()

    async def test_start_when_already_running_returns_error(
        self,
        async_client: AsyncClient,
        tunnel_config_factory,
        reset_tunnel_service,
        admin_headers,
    ):
        """Test that starting tunnel when already running returns error."""
        await tunnel_config_factory(
            name="Production",
            public_url="https://mcpbox.example.com",
            tunnel_token="eyJhIjoiYmxhaCIsInQiOiJ0b2tlbiJ9",
            is_active=True,
        )

        # Mock service that raises on start
        mock_service = MagicMock()
        mock_service.start = AsyncMock(side_effect=RuntimeError("Tunnel already running"))

        with override_tunnel_service(mock_service):
            response = await async_client.post("/api/tunnel/start", headers=admin_headers)

        assert response.status_code == 400
        data = response.json()
        assert "Failed to start tunnel" in data["detail"]


class TestTunnelStop:
    """Tests for POST /api/tunnel/stop endpoint."""

    async def test_stop_returns_disconnected_status(
        self, async_client: AsyncClient, reset_tunnel_service, admin_headers
    ):
        """Test that stopping tunnel returns disconnected status."""
        mock_service = MagicMock()
        mock_service.stop = AsyncMock(
            return_value={
                "status": "disconnected",
                "url": None,
                "started_at": None,
                "error": None,
            }
        )

        with override_tunnel_service(mock_service):
            response = await async_client.post("/api/tunnel/stop", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disconnected"
        mock_service.stop.assert_called_once()

    async def test_stop_when_not_running_still_succeeds(
        self, async_client: AsyncClient, reset_tunnel_service, admin_headers
    ):
        """Test that stopping when not running still returns success."""
        mock_service = MagicMock()
        mock_service.stop = AsyncMock(
            return_value={
                "status": "disconnected",
                "url": None,
                "started_at": None,
                "error": None,
            }
        )

        with override_tunnel_service(mock_service):
            response = await async_client.post("/api/tunnel/stop", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disconnected"

    async def test_stop_handles_service_error(
        self, async_client: AsyncClient, reset_tunnel_service, admin_headers
    ):
        """Test that stop handles service errors gracefully."""
        mock_service = MagicMock()
        mock_service.stop = AsyncMock(side_effect=Exception("Process termination failed"))

        with override_tunnel_service(mock_service):
            response = await async_client.post("/api/tunnel/stop", headers=admin_headers)

        assert response.status_code == 500
        data = response.json()
        assert "internal error" in data["detail"].lower()


class TestTunnelAuditLogging:
    """Tests for audit logging on tunnel operations."""

    async def test_start_logs_audit_entry(
        self,
        async_client: AsyncClient,
        tunnel_config_factory,
        reset_tunnel_service,
        admin_headers,
    ):
        """Test that starting tunnel creates an audit log entry."""
        await tunnel_config_factory(
            name="Production",
            public_url="https://mcpbox.example.com",
            tunnel_token="eyJhIjoiYmxhaCIsInQiOiJ0b2tlbiJ9",
            is_active=True,
        )

        mock_service = MagicMock()
        mock_service.start = AsyncMock(
            return_value={
                "status": "connected",
                "url": "https://mcpbox.example.com",
                "started_at": "2025-01-01T00:00:00Z",
            }
        )

        mock_audit = MagicMock()
        mock_audit.log_tunnel_action = AsyncMock()

        with override_tunnel_service(mock_service), override_audit_service(mock_audit):
            response = await async_client.post("/api/tunnel/start", headers=admin_headers)

        assert response.status_code == 200
        mock_audit.log_tunnel_action.assert_called_once()

        # Verify audit call details
        call_kwargs = mock_audit.log_tunnel_action.call_args[1]
        assert call_kwargs["details"]["configuration"] == "Production"

    async def test_stop_logs_audit_entry(
        self, async_client: AsyncClient, reset_tunnel_service, admin_headers
    ):
        """Test that stopping tunnel creates an audit log entry."""
        mock_service = MagicMock()
        mock_service.stop = AsyncMock(
            return_value={"status": "disconnected", "url": None, "started_at": None, "error": None}
        )

        mock_audit = MagicMock()
        mock_audit.log_tunnel_action = AsyncMock()

        with override_tunnel_service(mock_service), override_audit_service(mock_audit):
            response = await async_client.post("/api/tunnel/stop", headers=admin_headers)

        assert response.status_code == 200
        mock_audit.log_tunnel_action.assert_called_once()


class TestGetActiveConfiguration:
    """Tests for GET /api/tunnel/configurations/active/current endpoint."""

    async def test_returns_null_when_no_active(self, async_client: AsyncClient, admin_headers):
        """Test that endpoint returns null when no configuration is active."""
        response = await async_client.get(
            "/api/tunnel/configurations/active/current", headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json() is None

    async def test_returns_active_configuration(
        self, async_client: AsyncClient, tunnel_config_factory, admin_headers
    ):
        """Test that endpoint returns the active configuration."""
        # Create inactive and active configs
        await tunnel_config_factory(name="Inactive", is_active=False)
        active_config = await tunnel_config_factory(
            name="Active Config",
            public_url="https://active.example.com",
            is_active=True,
        )

        response = await async_client.get(
            "/api/tunnel/configurations/active/current", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data is not None
        assert data["name"] == "Active Config"
        assert data["public_url"] == "https://active.example.com"
        assert data["is_active"] is True
        assert str(active_config.id) == data["id"]
