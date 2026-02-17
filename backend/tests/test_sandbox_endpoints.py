"""Tests for sandbox API endpoints (backend side)."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.main import app
from app.services.sandbox_client import get_sandbox_client


@contextmanager
def override_sandbox_client(mock_client):
    """Context manager to override sandbox client dependency."""
    app.dependency_overrides[get_sandbox_client] = lambda: mock_client
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_sandbox_client, None)


class TestStartServer:
    """Tests for POST /sandbox/servers/{server_id}/start endpoint."""

    @pytest.mark.asyncio
    async def test_start_server_not_found(self, async_client: AsyncClient, admin_headers):
        """Test starting a non-existent server."""
        fake_id = uuid4()
        response = await async_client.post(
            f"/api/sandbox/servers/{fake_id}/start", headers=admin_headers
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_start_server_already_running(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test starting a server that is already running."""
        server = await server_factory(status="running")

        response = await async_client.post(
            f"/api/sandbox/servers/{server.id}/start", headers=admin_headers
        )

        assert response.status_code == 409
        assert "already running" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_start_server_no_tools(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test starting a server with no tools."""
        server = await server_factory(status="stopped")

        response = await async_client.post(
            f"/api/sandbox/servers/{server.id}/start", headers=admin_headers
        )

        assert response.status_code == 400
        assert "no tools" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_start_server_success(
        self,
        async_client: AsyncClient,
        server_factory,
        tool_factory,
        db_session,
        admin_headers,
    ):
        """Test successfully starting a server."""
        server = await server_factory(status="stopped")
        await tool_factory(server=server, name="test_tool")

        # Mock the sandbox client using dependency override
        mock_client = MagicMock()
        mock_client.register_server = AsyncMock(
            return_value={"success": True, "tools_registered": 1}
        )

        with override_sandbox_client(mock_client):
            response = await async_client.post(
                f"/api/sandbox/servers/{server.id}/start", headers=admin_headers
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["registered_tools"] == 1

    @pytest.mark.asyncio
    async def test_start_server_sandbox_failure(
        self, async_client: AsyncClient, server_factory, tool_factory, admin_headers
    ):
        """Test handling sandbox registration failure."""
        server = await server_factory(status="stopped")
        await tool_factory(server=server, name="test_tool")

        mock_client = MagicMock()
        mock_client.register_server = AsyncMock(
            return_value={"success": False, "error": "Sandbox error"}
        )

        with override_sandbox_client(mock_client):
            response = await async_client.post(
                f"/api/sandbox/servers/{server.id}/start", headers=admin_headers
            )

        assert response.status_code == 500


class TestStopServer:
    """Tests for POST /sandbox/servers/{server_id}/stop endpoint."""

    @pytest.mark.asyncio
    async def test_stop_server_not_found(self, async_client: AsyncClient, admin_headers):
        """Test stopping a non-existent server."""
        fake_id = uuid4()
        response = await async_client.post(
            f"/api/sandbox/servers/{fake_id}/stop", headers=admin_headers
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_stop_server_not_running(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test stopping a server that is not running."""
        server = await server_factory(status="stopped")

        response = await async_client.post(
            f"/api/sandbox/servers/{server.id}/stop", headers=admin_headers
        )

        assert response.status_code == 400
        assert "not running" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_stop_server_success(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test successfully stopping a server."""
        server = await server_factory(status="running")

        mock_client = MagicMock()
        mock_client.unregister_server = AsyncMock(return_value={"success": True})

        with override_sandbox_client(mock_client):
            response = await async_client.post(
                f"/api/sandbox/servers/{server.id}/stop", headers=admin_headers
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"


class TestRestartServer:
    """Tests for POST /sandbox/servers/{server_id}/restart endpoint."""

    @pytest.mark.asyncio
    async def test_restart_server_not_found(self, async_client: AsyncClient, admin_headers):
        """Test restarting a non-existent server."""
        fake_id = uuid4()
        response = await async_client.post(
            f"/api/sandbox/servers/{fake_id}/restart", headers=admin_headers
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_restart_server_no_tools(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test restarting a server with no tools."""
        server = await server_factory(status="running")

        mock_client = MagicMock()
        mock_client.unregister_server = AsyncMock(return_value={"success": True})

        with override_sandbox_client(mock_client):
            response = await async_client.post(
                f"/api/sandbox/servers/{server.id}/restart", headers=admin_headers
            )

        assert response.status_code == 400
        assert "no tools" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_restart_server_success(
        self, async_client: AsyncClient, server_factory, tool_factory, admin_headers
    ):
        """Test successfully restarting a server."""
        server = await server_factory(status="running")
        await tool_factory(server=server, name="test_tool")

        mock_client = MagicMock()
        mock_client.unregister_server = AsyncMock(return_value={"success": True})
        mock_client.register_server = AsyncMock(
            return_value={"success": True, "tools_registered": 1}
        )

        with override_sandbox_client(mock_client):
            response = await async_client.post(
                f"/api/sandbox/servers/{server.id}/restart", headers=admin_headers
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"


class TestGetServerStatus:
    """Tests for GET /sandbox/servers/{server_id}/status endpoint."""

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, async_client: AsyncClient, admin_headers):
        """Test getting status of non-existent server."""
        fake_id = uuid4()
        response = await async_client.get(
            f"/api/sandbox/servers/{fake_id}/status", headers=admin_headers
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_status_success(
        self, async_client: AsyncClient, server_factory, admin_headers
    ):
        """Test successfully getting server status."""
        server = await server_factory(status="running")

        mock_client = MagicMock()
        mock_client.list_tools = AsyncMock(return_value=[{"name": "tool1"}])

        with override_sandbox_client(mock_client):
            response = await async_client.get(
                f"/api/sandbox/servers/{server.id}/status", headers=admin_headers
            )

        assert response.status_code == 200
        data = response.json()
        assert data["server_id"] == str(server.id)
        assert data["status"] == "running"
        assert data["registered_tools"] == 1


class TestGetServerLogs:
    """Tests for GET /sandbox/servers/{server_id}/logs endpoint."""

    @pytest.mark.asyncio
    async def test_get_logs_not_found(self, async_client: AsyncClient, admin_headers):
        """Test getting logs of non-existent server."""
        fake_id = uuid4()
        response = await async_client.get(
            f"/api/sandbox/servers/{fake_id}/logs", headers=admin_headers
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_logs_success(self, async_client: AsyncClient, server_factory, admin_headers):
        """Test successfully getting server logs."""
        server = await server_factory()

        response = await async_client.get(
            f"/api/sandbox/servers/{server.id}/logs", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["server_id"] == str(server.id)
        assert "Activity" in data["message"]  # Points to Activity dashboard


class TestBuildToolDefinitions:
    """Tests for internal tool building functions."""

    def test_build_tool_definition(self):
        """Test building tool definition for Python code tools."""
        from app.api.sandbox import _build_tool_definitions

        tool = MagicMock()
        tool.name = "test_tool"
        tool.description = "Test description"
        tool.input_schema = {"type": "object", "properties": {}}
        tool.timeout_ms = 30000
        tool.python_code = "async def main(): return 'hello'"

        result = _build_tool_definitions([tool])

        assert len(result) == 1
        assert result[0]["name"] == "test_tool"
        assert result[0]["description"] == "Test description"
        assert result[0]["python_code"] == "async def main(): return 'hello'"
        assert result[0]["timeout_ms"] == 30000

    def test_build_tool_with_default_timeout(self):
        """Test building tool definition with default timeout."""
        from app.api.sandbox import _build_tool_definitions

        tool = MagicMock()
        tool.name = "py_tool"
        tool.description = "Python tool"
        tool.input_schema = {"type": "object"}
        tool.timeout_ms = None  # No timeout specified
        tool.python_code = "async def main(): return 'hello'"

        result = _build_tool_definitions([tool])

        assert len(result) == 1
        assert result[0]["name"] == "py_tool"
        assert result[0]["python_code"] == "async def main(): return 'hello'"
        assert result[0]["timeout_ms"] == 30000  # Default timeout


class TestSecretSyncToSandbox:
    """Tests that secrets are synced to the sandbox when set/updated/deleted."""

    @pytest.mark.asyncio
    async def test_set_secret_syncs_to_sandbox_when_running(
        self, async_client: AsyncClient, server_factory, db_session, admin_headers
    ):
        """Setting a secret on a running server syncs to sandbox."""
        from app.models.server_secret import ServerSecret

        server = await server_factory(status="running")

        # Create a secret placeholder
        secret = ServerSecret(
            server_id=server.id,
            key_name="API_KEY",
            description="Test API key",
        )
        db_session.add(secret)
        await db_session.flush()

        mock_client = MagicMock()
        mock_client.update_server_secrets = AsyncMock(return_value={"success": True})

        with override_sandbox_client(mock_client):
            response = await async_client.put(
                f"/api/servers/{server.id}/secrets/API_KEY",
                json={"value": "my-secret-value"},
                headers=admin_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["has_value"] is True

        # Verify sandbox was called with the decrypted secrets
        mock_client.update_server_secrets.assert_called_once()
        call_args = mock_client.update_server_secrets.call_args
        assert call_args.args[0] == str(server.id)
        # The secrets dict should contain the decrypted value
        assert "API_KEY" in call_args.args[1]

    @pytest.mark.asyncio
    async def test_set_secret_skips_sync_when_stopped(
        self, async_client: AsyncClient, server_factory, db_session, admin_headers
    ):
        """Setting a secret on a stopped server does NOT sync to sandbox."""
        from app.models.server_secret import ServerSecret

        server = await server_factory(status="stopped")

        secret = ServerSecret(
            server_id=server.id,
            key_name="API_KEY",
            description="Test API key",
        )
        db_session.add(secret)
        await db_session.flush()

        mock_client = MagicMock()
        mock_client.update_server_secrets = AsyncMock(return_value={"success": True})

        with override_sandbox_client(mock_client):
            response = await async_client.put(
                f"/api/servers/{server.id}/secrets/API_KEY",
                json={"value": "my-secret-value"},
                headers=admin_headers,
            )

        assert response.status_code == 200
        # Sandbox should NOT have been called
        mock_client.update_server_secrets.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_secret_syncs_to_sandbox_when_running(
        self, async_client: AsyncClient, server_factory, db_session, admin_headers
    ):
        """Deleting a secret on a running server syncs to sandbox."""
        from app.models.server_secret import ServerSecret
        from app.services.crypto import encrypt

        server = await server_factory(status="running")

        secret = ServerSecret(
            server_id=server.id,
            key_name="OLD_KEY",
            description="Key to delete",
            encrypted_value=encrypt("old-value"),
        )
        db_session.add(secret)
        await db_session.flush()

        mock_client = MagicMock()
        mock_client.update_server_secrets = AsyncMock(return_value={"success": True})

        with override_sandbox_client(mock_client):
            response = await async_client.delete(
                f"/api/servers/{server.id}/secrets/OLD_KEY",
                headers=admin_headers,
            )

        assert response.status_code == 204

        # Verify sandbox was called with empty secrets (the deleted key removed)
        mock_client.update_server_secrets.assert_called_once()
        call_args = mock_client.update_server_secrets.call_args
        assert call_args.args[0] == str(server.id)
        assert "OLD_KEY" not in call_args.args[1]
