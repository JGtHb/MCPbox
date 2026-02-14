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


class TestBuildCredentialsList:
    """Tests for credential list building."""

    def test_build_api_key_header_credential(self):
        """Test building API key header credential."""
        from app.api.sandbox import _build_credentials_list

        cred = MagicMock()
        cred.name = "API_KEY"
        cred.auth_type = "api_key_header"
        cred.header_name = "X-API-Key"
        cred.query_param_name = None
        cred.value = "encrypted_key"
        cred.access_token = None
        cred.username = None
        cred.password = None

        result = _build_credentials_list([cred])

        assert len(result) == 1
        assert result[0]["name"] == "API_KEY"
        assert result[0]["auth_type"] == "api_key_header"
        assert result[0]["value"] == "encrypted_key"

    def test_build_bearer_credential(self):
        """Test building bearer token credential."""
        from app.api.sandbox import _build_credentials_list

        cred = MagicMock()
        cred.name = "BEARER"
        cred.auth_type = "bearer"
        cred.header_name = None
        cred.query_param_name = None
        cred.value = None
        cred.access_token = "encrypted_token"
        cred.username = None
        cred.password = None

        result = _build_credentials_list([cred])

        assert result[0]["auth_type"] == "bearer"
        assert result[0]["value"] == "encrypted_token"

    def test_build_basic_auth_credential(self):
        """Test building basic auth credential."""
        from app.api.sandbox import _build_credentials_list

        cred = MagicMock()
        cred.name = "BASIC"
        cred.auth_type = "basic"
        cred.header_name = None
        cred.query_param_name = None
        cred.value = None
        cred.access_token = None
        cred.username = "encrypted_user"
        cred.password = "encrypted_pass"

        result = _build_credentials_list([cred])

        assert result[0]["auth_type"] == "basic"
        assert result[0]["username"] == "encrypted_user"
        assert result[0]["password"] == "encrypted_pass"

    def test_build_oauth2_credential(self):
        """Test building OAuth2 credential."""
        from app.api.sandbox import _build_credentials_list

        cred = MagicMock()
        cred.name = "OAUTH"
        cred.auth_type = "oauth2"
        cred.header_name = None
        cred.query_param_name = None
        cred.value = None
        cred.access_token = "encrypted_oauth_token"
        cred.username = None
        cred.password = None

        result = _build_credentials_list([cred])

        assert result[0]["auth_type"] == "oauth2"
        assert result[0]["value"] == "encrypted_oauth_token"
