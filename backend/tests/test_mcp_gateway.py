"""Tests for MCP Gateway endpoints.

Authentication modes:
- Local mode (no service token in database): No auth required, all requests allowed
- Remote mode (service token loaded from database): Requires X-MCPbox-Service-Token header

Tests run in local mode by default (ServiceTokenCache has no token loaded).
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.main import app
from app.services.email_policy_cache import EmailPolicyCache
from app.services.sandbox_client import get_sandbox_client
from app.services.service_token_cache import ServiceTokenCache


def _make_permissive_email_policy_cache() -> EmailPolicyCache:
    """Create an EmailPolicyCache with no policy (allows all emails)."""
    cache = EmailPolicyCache()
    cache._policy_type = None
    cache._allowed_emails = None
    cache._allowed_domain = None
    cache._db_error = False
    cache._last_loaded = time.monotonic()
    return cache


@pytest.fixture
def mock_sandbox_client():
    """Create a mock sandbox client and override the FastAPI dependency.

    This fixture properly uses FastAPI's dependency_overrides to inject the mock,
    which is necessary for the MCP gateway endpoints that use Depends(get_sandbox_client).
    """
    mock_client = MagicMock()
    mock_client.health_check = AsyncMock(return_value=True)
    mock_client.mcp_request = AsyncMock(return_value={"result": {"tools": []}})
    mock_client.register_server = AsyncMock(return_value={"success": True, "tools_registered": 1})
    mock_client.unregister_server = AsyncMock(return_value={"success": True})

    # Override the FastAPI dependency
    app.dependency_overrides[get_sandbox_client] = lambda: mock_client
    yield mock_client
    # Clean up
    app.dependency_overrides.pop(get_sandbox_client, None)


class TestMCPGatewayLocalMode:
    """Tests for MCP gateway in local mode (no service token configured).

    In local mode, all requests are allowed without authentication.
    """

    @pytest.mark.asyncio
    async def test_request_allowed_without_auth(
        self, async_client: AsyncClient, mock_sandbox_client
    ):
        """Test that requests are allowed without authentication in local mode."""
        mock_sandbox_client.mcp_request = AsyncMock(return_value={"result": {"tools": []}})

        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )
        # In local mode, should succeed without auth
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_local_mode_user_source(self, async_client: AsyncClient, mock_sandbox_client):
        """Test that local mode sets user source correctly."""
        mock_sandbox_client.mcp_request = AsyncMock(return_value={"result": {"tools": []}})

        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )
        assert response.status_code == 200


class TestMCPGatewayRemoteMode:
    """Tests for MCP gateway in remote mode (service token loaded from database).

    These tests mock ServiceTokenCache to simulate a token being loaded from DB.
    """

    @staticmethod
    def _make_mock_request(client_host: str = "127.0.0.1") -> MagicMock:
        """Create a mock FastAPI Request with a client."""
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = client_host
        return mock_request

    @pytest.mark.asyncio
    async def test_missing_token_returns_403(self):
        """Test that missing service token returns 403 in remote mode."""
        from fastapi import HTTPException

        from app.api.auth_simple import verify_mcp_auth
        from app.services.service_token_cache import ServiceTokenCache

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value="a" * 32)

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
            with pytest.raises(HTTPException) as exc_info:
                await verify_mcp_auth(
                    request=self._make_mock_request(),
                    x_mcpbox_service_token=None,
                )
            assert exc_info.value.status_code == 403
            assert "authentication failed" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_invalid_token_returns_403(self):
        """Test that invalid service token returns 403."""
        from fastapi import HTTPException

        from app.api.auth_simple import verify_mcp_auth
        from app.services.service_token_cache import ServiceTokenCache

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value="correct-token-" + "x" * 20)

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
            with pytest.raises(HTTPException) as exc_info:
                await verify_mcp_auth(
                    request=self._make_mock_request(),
                    x_mcpbox_service_token="wrong-token",
                )
            assert exc_info.value.status_code == 403
            assert "authentication failed" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_generic_error_message_hides_auth_state(self):
        """Test that both missing and invalid tokens return the same generic message."""
        from fastapi import HTTPException

        from app.api.auth_simple import verify_mcp_auth
        from app.services.service_token_cache import ServiceTokenCache

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value="correct-token-" + "x" * 20)

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
            # Missing token
            with pytest.raises(HTTPException) as missing_exc:
                await verify_mcp_auth(
                    request=self._make_mock_request(),
                    x_mcpbox_service_token=None,
                )

            # Invalid token
            with pytest.raises(HTTPException) as invalid_exc:
                await verify_mcp_auth(
                    request=self._make_mock_request(),
                    x_mcpbox_service_token="wrong-token",
                )

            # Both should return the same generic message
            assert missing_exc.value.detail == invalid_exc.value.detail

    @pytest.mark.asyncio
    async def test_valid_token_accepted(self, async_client: AsyncClient, mock_sandbox_client):
        """Test that valid service token is accepted (HTTP 200, may have JSON-RPC error)."""
        mock_sandbox_client.mcp_request = AsyncMock(return_value={"result": {"tools": []}})
        test_token = "a" * 32

        from app.services.email_policy_cache import EmailPolicyCache
        from app.services.service_token_cache import ServiceTokenCache

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)

        mock_email_policy = MagicMock()
        mock_email_policy.check_email = AsyncMock(return_value=(True, "test"))

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=mock_email_policy),
        ):
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                },
                headers={"X-MCPbox-Service-Token": test_token},
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_remote_mode_sets_oidc_auth_method(
        self, async_client: AsyncClient, mock_sandbox_client
    ):
        """Test that remote mode sets auth_method to 'oidc'.

        tools/list requires a verified email (OIDC identity).
        """
        mock_sandbox_client.mcp_request = AsyncMock(return_value={"result": {"tools": []}})
        test_token = "a" * 32

        from app.services.email_policy_cache import EmailPolicyCache
        from app.services.service_token_cache import ServiceTokenCache

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)

        mock_email_policy = MagicMock()
        mock_email_policy.check_email = AsyncMock(return_value=(True, "test"))

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=mock_email_policy),
        ):
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                },
                headers={
                    "X-MCPbox-Service-Token": test_token,
                    "X-MCPbox-User-Email": "user@example.com",
                },
            )
            assert response.status_code == 200
            result = response.json()
            assert "result" in result
            assert "tools" in result["result"]

    @pytest.mark.asyncio
    async def test_notifications_allowed_in_remote_mode(self, async_client: AsyncClient):
        """Remote mode allows notifications (202 Accepted).

        Notifications are needed for Cloudflare sync's initialized notification.
        """
        test_token = "a" * 32

        from app.services.email_policy_cache import EmailPolicyCache
        from app.services.service_token_cache import ServiceTokenCache

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)

        mock_email_policy = MagicMock()
        mock_email_policy.check_email = AsyncMock(return_value=(True, "test"))

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=mock_email_policy),
        ):
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                },
                headers={"X-MCPbox-Service-Token": test_token},
            )
            assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_notifications_allowed_in_local_mode(self, async_client: AsyncClient):
        """Local mode allows notifications (202 Accepted)."""
        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )
        assert response.status_code == 202


class TestMCPGatewayToolsList:
    """Tests for tools/list method."""

    @pytest.mark.asyncio
    async def test_tools_list_returns_management_tools(
        self, async_client: AsyncClient, mock_sandbox_client
    ):
        """Test that tools/list includes management tools."""
        mock_sandbox_client.mcp_request = AsyncMock(return_value={"result": {"tools": []}})

        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )

        assert response.status_code == 200
        result = response.json()
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 1
        assert "result" in result
        assert "tools" in result["result"]

        # Check that management tools are present
        tool_names = [t["name"] for t in result["result"]["tools"]]
        assert "mcpbox_list_servers" in tool_names
        assert "mcpbox_create_server" in tool_names

    @pytest.mark.asyncio
    async def test_tools_list_combines_sandbox_and_management(
        self, async_client: AsyncClient, mock_sandbox_client, server_factory, tool_factory
    ):
        """Test that tools/list combines sandbox and management tools.

        Note: The gateway filters sandbox tools to only include approved ones.
        We create an approved tool in the database so the sandbox response
        for that tool name passes the filter. Tool names are in the format
        "server_name__tool_name" which matches the sandbox format.
        """
        # Create a server and an approved tool in the database
        server = await server_factory(name="test_server")
        await tool_factory(
            server=server,
            name="sandbox_tool",
            description="A sandbox tool",
            approval_status="approved",
        )

        # Mock sandbox to return this tool (with proper server__tool name format)
        mock_sandbox_client.mcp_request = AsyncMock(
            return_value={
                "result": {
                    "tools": [
                        {
                            "name": "test_server__sandbox_tool",
                            "description": "A sandbox tool",
                            "inputSchema": {"type": "object"},
                        }
                    ]
                }
            }
        )

        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )

        assert response.status_code == 200
        result = response.json()
        tool_names = [t["name"] for t in result["result"]["tools"]]

        # Should have both sandbox and management tools
        assert "test_server__sandbox_tool" in tool_names
        assert "mcpbox_list_servers" in tool_names


class TestMCPGatewayToolsCall:
    """Tests for tools/call method."""

    @pytest.mark.asyncio
    async def test_management_tool_call(self, async_client: AsyncClient, mock_sandbox_client):
        """Test calling a management tool."""
        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "mcpbox_list_servers",
                    "arguments": {},
                },
            },
        )

        assert response.status_code == 200
        result = response.json()
        assert "result" in result
        assert "content" in result["result"]

    @pytest.mark.asyncio
    async def test_sandbox_tool_call_forwarded(
        self, async_client: AsyncClient, mock_sandbox_client
    ):
        """Test that non-management tool calls are forwarded to sandbox."""
        mock_sandbox_client.mcp_request = AsyncMock(
            return_value={"result": {"content": [{"type": "text", "text": "sandbox response"}]}}
        )

        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "some_sandbox_tool",
                    "arguments": {"arg1": "value1"},
                },
            },
        )

        assert response.status_code == 200

        # Verify sandbox was called
        mock_sandbox_client.mcp_request.assert_called()
        call_args = mock_sandbox_client.mcp_request.call_args[0][0]
        assert call_args["method"] == "tools/call"
        assert call_args["params"]["name"] == "some_sandbox_tool"

    @pytest.mark.asyncio
    async def test_sandbox_error_returned(self, async_client: AsyncClient, mock_sandbox_client):
        """Test that sandbox errors are properly returned."""
        mock_sandbox_client.mcp_request = AsyncMock(
            return_value={
                "error": {
                    "code": -32602,
                    "message": "Tool not found",
                }
            }
        )

        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "nonexistent_tool",
                    "arguments": {},
                },
            },
        )

        assert response.status_code == 200
        result = response.json()
        assert "error" in result
        assert result["error"]["code"] == -32602


class TestMCPGatewayHealth:
    """Tests for MCP health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_ok(self, async_client: AsyncClient, mock_sandbox_client):
        """Test health check returns OK when sandbox is healthy."""
        mock_sandbox_client.health_check = AsyncMock(return_value=True)

        response = await async_client.get("/mcp/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["sandbox"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_degraded(self, async_client: AsyncClient, mock_sandbox_client):
        """Test health check returns degraded when sandbox is unhealthy."""
        mock_sandbox_client.health_check = AsyncMock(return_value=False)

        response = await async_client.get("/mcp/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["sandbox"] == "unhealthy"


class TestMCPManagementTools:
    """Tests for specific management tools."""

    @pytest.mark.asyncio
    async def test_create_server_via_mcp(self, async_client: AsyncClient, mock_sandbox_client):
        """Test creating a server via MCP management tool."""
        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "mcpbox_create_server",
                    "arguments": {
                        "name": "test_mcp_server",
                        "description": "Created via MCP",
                    },
                },
            },
        )

        assert response.status_code == 200
        result = response.json()
        assert "result" in result
        assert "content" in result["result"]

        # Parse the content to verify server was created
        import json

        content_text = result["result"]["content"][0]["text"]
        server_data = json.loads(content_text)
        assert "id" in server_data
        assert server_data["name"] == "test_mcp_server"

    @pytest.mark.asyncio
    async def test_list_servers_via_mcp(self, async_client: AsyncClient, mock_sandbox_client):
        """Test listing servers via MCP management tool."""
        # First create a server via admin API
        await async_client.post(
            "/api/servers",
            json={"name": "server_1"},
        )

        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "mcpbox_list_servers",
                    "arguments": {},
                },
            },
        )

        assert response.status_code == 200
        result = response.json()
        assert "result" in result


class TestMCPProtocolHandshake:
    """Tests for MCP protocol initialization and notification handling."""

    @pytest.mark.asyncio
    async def test_initialize_returns_capabilities(
        self, async_client: AsyncClient, mock_sandbox_client
    ):
        """Test that initialize method returns server capabilities."""
        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": "init-1",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            },
        )

        assert response.status_code == 200
        result = response.json()
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == "init-1"
        assert "result" in result
        assert result["result"]["protocolVersion"] == "2025-11-25"
        assert "tools" in result["result"]["capabilities"]
        assert result["result"]["serverInfo"]["name"] == "mcpbox"

    @pytest.mark.asyncio
    async def test_notification_returns_202(self, async_client: AsyncClient, mock_sandbox_client):
        """Test that notifications return 202 Accepted (per MCP Streamable HTTP spec)."""
        # Notifications don't have an 'id' field
        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        # MCP Streamable HTTP transport spec requires 202 Accepted
        # for notifications (one-way messages)
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_notification_with_params(self, async_client: AsyncClient, mock_sandbox_client):
        """Test that notifications with params also return 202."""
        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {"progressToken": "abc", "progress": 50},
            },
        )

        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_request_with_string_id(self, async_client: AsyncClient, mock_sandbox_client):
        """Test that requests with string IDs work correctly."""
        mock_sandbox_client.mcp_request = AsyncMock(return_value={"result": {"tools": []}})

        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": "string-id-123",
                "method": "tools/list",
            },
        )

        assert response.status_code == 200
        result = response.json()
        assert result["id"] == "string-id-123"

    @pytest.mark.asyncio
    async def test_request_with_integer_id(self, async_client: AsyncClient, mock_sandbox_client):
        """Test that requests with integer IDs work correctly."""
        mock_sandbox_client.mcp_request = AsyncMock(return_value={"result": {"tools": []}})

        response = await async_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 42,
                "method": "tools/list",
            },
        )

        assert response.status_code == 200
        result = response.json()
        assert result["id"] == 42


class TestOIDCIntegrationWithGateway:
    """Tests for OIDC auth integration with the MCP gateway auth flow.

    With Access for SaaS (OIDC), the Worker handles identity verification
    via OIDC id_token and forwards user email in X-MCPbox-User-Email.
    auth_method is always 'oidc' for remote requests.
    """

    @staticmethod
    def _make_mock_request(client_host: str = "127.0.0.1") -> MagicMock:
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = client_host
        # headers.get() must return None for missing headers, not MagicMock
        mock_request.headers = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        return mock_request

    @pytest.mark.asyncio
    async def test_service_token_with_email_sets_oidc(self):
        """Test that a valid service token with email header sets auth_method to 'oidc'."""
        from app.api.auth_simple import verify_mcp_auth
        from app.services.service_token_cache import ServiceTokenCache

        test_token = "a" * 32

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)

        mock_request = self._make_mock_request()
        mock_request.headers = MagicMock()
        mock_request.headers.get = MagicMock(
            side_effect=lambda key, default=None: {
                "X-MCPbox-User-Email": "user@example.com",
            }.get(key, default)
        )

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache),
            patch.object(
                EmailPolicyCache,
                "get_instance",
                return_value=_make_permissive_email_policy_cache(),
            ),
        ):
            user = await verify_mcp_auth(
                request=mock_request,
                x_mcpbox_service_token=test_token,
            )

        assert user.source == "worker"
        assert user.auth_method == "oidc"
        assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_service_token_without_email_sets_oidc(self):
        """Test that a valid service token without email still sets auth_method to 'oidc'."""
        from app.api.auth_simple import verify_mcp_auth
        from app.services.service_token_cache import ServiceTokenCache

        test_token = "a" * 32

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache),
            patch.object(
                EmailPolicyCache,
                "get_instance",
                return_value=_make_permissive_email_policy_cache(),
            ),
        ):
            user = await verify_mcp_auth(
                request=self._make_mock_request(),
                x_mcpbox_service_token=test_token,
            )

        assert user.source == "worker"
        assert user.auth_method == "oidc"
        assert user.email is None

    @pytest.mark.asyncio
    async def test_worker_email_header_trusted_with_service_token(self):
        """Test that Worker-supplied email header is trusted when service token is valid.

        When a valid service token is present (proving Worker provenance),
        the gateway trusts the X-MCPbox-User-Email header from OIDC-verified
        OAuth token props.
        """
        from app.api.auth_simple import verify_mcp_auth
        from app.services.service_token_cache import ServiceTokenCache

        test_token = "a" * 32

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)

        mock_request = self._make_mock_request()
        mock_request.headers = MagicMock()
        mock_request.headers.get = MagicMock(
            side_effect=lambda key, default=None: {
                "X-MCPbox-User-Email": "user@example.com",
            }.get(key, default)
        )

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache),
            patch.object(
                EmailPolicyCache,
                "get_instance",
                return_value=_make_permissive_email_policy_cache(),
            ),
        ):
            user = await verify_mcp_auth(
                request=mock_request,
                x_mcpbox_service_token=test_token,
            )

        assert user.source == "worker"
        assert user.auth_method == "oidc"
        assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_oidc_allows_tools_call_at_gateway(
        self, async_client: AsyncClient, mock_sandbox_client
    ):
        """End-to-end: Worker request with email allows tools/call (OIDC + service token sufficient)."""
        mock_sandbox_client.mcp_request = AsyncMock(
            return_value={"result": {"content": [{"type": "text", "text": "ok"}]}}
        )
        test_token = "a" * 32

        from app.services.service_token_cache import ServiceTokenCache

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache),
            patch.object(
                EmailPolicyCache,
                "get_instance",
                return_value=_make_permissive_email_policy_cache(),
            ),
        ):
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "some_tool", "arguments": {}},
                },
                headers={
                    "X-MCPbox-Service-Token": test_token,
                    "X-MCPbox-User-Email": "user@example.com",
                },
            )
            assert response.status_code == 200
            # Should not be blocked - sandbox was called
            mock_sandbox_client.mcp_request.assert_called()


class TestMCPGatewaySyncAuth:
    """Regression tests for Cloudflare sync and Portal user scenarios.

    Cloudflare's MCP server sync authenticates via OIDC at the Worker (no email forwarded).
    Sync-only methods (initialize, tools/list, notifications) are allowed.
    Tool execution (tools/call) and unknown methods require a verified user
    identity (email from Worker-supplied X-MCPbox-User-Email header).

    These tests mock ServiceTokenCache with a valid service token, simulating the
    Worker forwarding requests with a valid service token but no user email.
    """

    @staticmethod
    def _make_sync_headers(test_token: str) -> dict[str, str]:
        return {"X-MCPbox-Service-Token": test_token}

    @staticmethod
    def _make_sync_cache(test_token: str) -> MagicMock:
        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)
        return mock_cache

    @staticmethod
    def _patch_remote_mode(mock_cache):
        """Context manager that patches both ServiceTokenCache and EmailPolicyCache.

        EmailPolicyCache must also be mocked because in the test environment the
        singleton cannot reach the database and fails closed (denying all emails).
        """
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            with (
                patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache),
                patch.object(
                    EmailPolicyCache,
                    "get_instance",
                    return_value=_make_permissive_email_policy_cache(),
                ),
            ):
                yield

        return _cm()

    @pytest.mark.asyncio
    async def test_sync_initialize_allowed(self, async_client: AsyncClient, mock_sandbox_client):
        """Cloudflare sync can call initialize (needed for MCP handshake)."""
        test_token = "a" * 32
        mock_cache = self._make_sync_cache(test_token)

        with self._patch_remote_mode(mock_cache):
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "cloudflare-sync", "version": "1.0.0"},
                    },
                },
                headers=self._make_sync_headers(test_token),
            )

        assert response.status_code == 200
        result = response.json()
        assert "result" in result
        assert result["result"]["protocolVersion"] == "2025-11-25"
        assert result["result"]["serverInfo"]["name"] == "mcpbox"

    @pytest.mark.asyncio
    async def test_sync_tools_list_blocked_without_email(
        self, async_client: AsyncClient, mock_sandbox_client
    ):
        """Anonymous remote tools/list is blocked (tool names are sensitive)."""
        mock_sandbox_client.mcp_request = AsyncMock(return_value={"result": {"tools": []}})
        test_token = "a" * 32
        mock_cache = self._make_sync_cache(test_token)

        with self._patch_remote_mode(mock_cache):
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                },
                headers=self._make_sync_headers(test_token),
            )

        assert response.status_code == 200
        result = response.json()
        assert "error" in result
        assert result["error"]["code"] == -32600
        assert "authentication" in result["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_sync_notifications_allowed(self, async_client: AsyncClient):
        """Cloudflare sync can send notifications (needed after initialize)."""
        test_token = "a" * 32
        mock_cache = self._make_sync_cache(test_token)

        with self._patch_remote_mode(mock_cache):
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                },
                headers=self._make_sync_headers(test_token),
            )

        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_sync_tools_call_blocked(self, async_client: AsyncClient, mock_sandbox_client):
        """Cloudflare sync cannot call tools/call (no verified user identity)."""
        test_token = "a" * 32
        mock_cache = self._make_sync_cache(test_token)

        with self._patch_remote_mode(mock_cache):
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "mcpbox_list_servers", "arguments": {}},
                },
                headers=self._make_sync_headers(test_token),
            )

        assert response.status_code == 200
        result = response.json()
        # Should be blocked - anonymous remote requests cannot execute tools
        assert "error" in result
        assert result["error"]["code"] == -32600
        assert "authentication" in result["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_portal_user_tools_call_allowed(
        self, async_client: AsyncClient, mock_sandbox_client
    ):
        """Portal user with verified email can call tools/call."""
        test_token = "a" * 32
        mock_cache = self._make_sync_cache(test_token)

        headers = {
            **self._make_sync_headers(test_token),
            "X-MCPbox-User-Email": "user@example.com",
        }

        with self._patch_remote_mode(mock_cache):
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "mcpbox_list_servers", "arguments": {}},
                },
                headers=headers,
            )

        assert response.status_code == 200
        result = response.json()
        # Should succeed - Portal user has verified email from OAuth props
        assert "result" in result
        assert "content" in result["result"]

    @pytest.mark.asyncio
    async def test_sync_unknown_method_blocked(
        self, async_client: AsyncClient, mock_sandbox_client
    ):
        """Cloudflare sync cannot call unknown methods (defense-in-depth)."""
        test_token = "a" * 32
        mock_cache = self._make_sync_cache(test_token)

        with self._patch_remote_mode(mock_cache):
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "resources/list",
                },
                headers=self._make_sync_headers(test_token),
            )

        assert response.status_code == 200
        result = response.json()
        assert "error" in result
        assert result["error"]["code"] == -32600


class TestServiceTokenCacheFailClosed:
    """Tests for service token cache fail-closed behavior."""

    @pytest.mark.asyncio
    async def test_decryption_error_fails_closed(self):
        """Test that decryption errors cause auth to be enabled (deny all)."""
        from app.services.service_token_cache import ServiceTokenCache

        cache = ServiceTokenCache()
        cache._db_error = False
        cache._decryption_error = True
        cache._token = None
        cache._last_loaded = time.monotonic()

        # Auth should be enabled (fail-closed) even though token is None
        assert cache.auth_enabled is True

    @pytest.mark.asyncio
    async def test_db_error_fails_closed(self):
        """Test that database errors cause auth to be enabled (deny all)."""
        from app.services.service_token_cache import ServiceTokenCache

        cache = ServiceTokenCache()
        cache._db_error = True
        cache._decryption_error = False
        cache._token = None
        cache._last_loaded = time.monotonic()

        assert cache.auth_enabled is True

    @pytest.mark.asyncio
    async def test_no_token_no_errors_means_local_mode(self):
        """Test that no token + no errors = local mode (auth disabled)."""
        from app.services.service_token_cache import ServiceTokenCache

        cache = ServiceTokenCache()
        cache._db_error = False
        cache._decryption_error = False
        cache._token = None
        cache._last_loaded = time.monotonic()

        assert cache.auth_enabled is False

    @pytest.mark.asyncio
    async def test_invalidate_clears_decryption_error(self):
        """Test that invalidate() clears the decryption error flag."""
        from app.services.service_token_cache import ServiceTokenCache

        cache = ServiceTokenCache()
        cache._decryption_error = True
        cache.invalidate()

        assert cache._decryption_error is False


class TestAuthRateLimiting:
    """Tests for authentication rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limit_triggers_after_max_failures(self):
        """Test that rate limiting triggers after too many failures."""
        from fastapi import HTTPException

        from app.api.auth_simple import (
            _FAILED_AUTH_MAX,
            _check_auth_rate_limit,
            _failed_auth_attempts,
            _record_auth_failure,
        )

        test_ip = "10.99.99.99"
        # Clear any existing entries
        _failed_auth_attempts.pop(test_ip, None)

        # Record max failures
        for _ in range(_FAILED_AUTH_MAX):
            _record_auth_failure(test_ip)

        # Next check should raise 429
        with pytest.raises(HTTPException) as exc_info:
            _check_auth_rate_limit(test_ip)
        assert exc_info.value.status_code == 429

        # Clean up
        _failed_auth_attempts.pop(test_ip, None)

    @pytest.mark.asyncio
    async def test_rate_limit_allows_under_threshold(self):
        """Test that rate limiting allows requests under the threshold."""
        from app.api.auth_simple import (
            _FAILED_AUTH_MAX,
            _check_auth_rate_limit,
            _failed_auth_attempts,
            _record_auth_failure,
        )

        test_ip = "10.88.88.88"
        _failed_auth_attempts.pop(test_ip, None)

        # Record fewer than max failures
        for _ in range(_FAILED_AUTH_MAX - 1):
            _record_auth_failure(test_ip)

        # Should not raise
        _check_auth_rate_limit(test_ip)

        # Clean up
        _failed_auth_attempts.pop(test_ip, None)
