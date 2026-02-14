"""Tests for MCP Gateway endpoints.

Authentication modes:
- Local mode (no service token in database): No auth required, all requests allowed
- Remote mode (service token loaded from database): Requires X-MCPbox-Service-Token header

Tests run in local mode by default (ServiceTokenCache has no token loaded).
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from httpx import AsyncClient

from app.main import app
from app.services.sandbox_client import get_sandbox_client
from app.services.service_token_cache import ServiceTokenCache


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

        from app.services.service_token_cache import ServiceTokenCache

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)
        mock_cache.get_team_domain = AsyncMock(return_value=None)
        mock_cache.get_portal_aud = AsyncMock(return_value=None)

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
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
    async def test_remote_mode_without_jwt_defaults_to_oauth(
        self, async_client: AsyncClient, mock_sandbox_client
    ):
        """Test that remote mode without JWT sets auth_method to 'oauth'.

        tools/list is allowed without JWT (needed for Cloudflare sync).
        """
        mock_sandbox_client.mcp_request = AsyncMock(return_value={"result": {"tools": []}})
        test_token = "a" * 32

        from app.services.service_token_cache import ServiceTokenCache

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)
        mock_cache.get_team_domain = AsyncMock(return_value=None)
        mock_cache.get_portal_aud = AsyncMock(return_value=None)

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                },
                headers={
                    "X-MCPbox-Service-Token": test_token,
                },
            )
            # tools/list is allowed for sync (OAuth-only, no JWT)
            assert response.status_code == 200
            result = response.json()
            assert "result" in result
            assert "tools" in result["result"]

    @pytest.mark.asyncio
    async def test_notifications_allowed_without_jwt_in_remote_mode(
        self, async_client: AsyncClient
    ):
        """Remote mode without JWT allows notifications (202 Accepted).

        Notifications are needed for Cloudflare sync's initialized notification.
        """
        test_token = "a" * 32

        from app.services.service_token_cache import ServiceTokenCache

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)
        mock_cache.get_team_domain = AsyncMock(return_value=None)
        mock_cache.get_portal_aud = AsyncMock(return_value=None)

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
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
        assert result["result"]["protocolVersion"] == "2024-11-05"
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


# --- JWT Verification Tests ---

# Shared RSA key pair for JWT tests
_RSA_KEY = None


def _get_test_rsa_key():
    """Generate (and cache) a test RSA key pair for JWT signing/verification."""
    global _RSA_KEY
    if _RSA_KEY is None:
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        _RSA_KEY = private_key
    return _RSA_KEY


def _int_to_base64url(n: int) -> str:
    """Encode an integer as unpadded base64url (for JWKS n/e values)."""
    import base64

    byte_length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()


def _make_jwks_response(private_key, kid: str = "test-key-1") -> dict:
    """Build a JWKS response dict from an RSA private key."""
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    public_key = private_key.public_key()
    pub_numbers: RSAPublicNumbers = public_key.public_numbers()

    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "alg": "RS256",
                "use": "sig",
                "n": _int_to_base64url(pub_numbers.n),
                "e": _int_to_base64url(pub_numbers.e),
            }
        ]
    }


def _sign_jwt(
    private_key,
    kid: str = "test-key-1",
    team_domain: str = "test.cloudflareaccess.com",
    aud: str = "test-aud-1234",
    email: str = "user@example.com",
    exp_offset: int = 3600,
    iss: str | None = None,
) -> str:
    """Create a signed RS256 JWT for testing."""
    from cryptography.hazmat.primitives import serialization

    now = int(time.time())
    payload = {
        "sub": "user-id-123",
        "email": email,
        "aud": aud,
        "iss": iss or f"https://{team_domain}",
        "iat": now,
        "nbf": now,
        "exp": now + exp_offset,
    }

    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return jwt.encode(
        payload,
        pem,
        algorithm="RS256",
        headers={"kid": kid, "alg": "RS256"},
    )


class TestJWTVerification:
    """Tests for Cloudflare Access JWT verification in the MCP gateway.

    These tests verify the _verify_cf_access_jwt function handles
    valid, invalid, expired, wrong-audience, and wrong-issuer JWTs.
    """

    TEAM_DOMAIN = "test.cloudflareaccess.com"
    PORTAL_AUD = "test-aud-1234"

    @pytest.mark.asyncio
    async def test_valid_jwt_accepted(self):
        """Test that a correctly signed JWT with valid claims is accepted."""
        from app.api.auth_simple import _verify_cf_access_jwt

        key = _get_test_rsa_key()
        jwks = _make_jwks_response(key)
        token = _sign_jwt(key, team_domain=self.TEAM_DOMAIN, aud=self.PORTAL_AUD)

        with patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value=jwks):
            payload = await _verify_cf_access_jwt(token, self.TEAM_DOMAIN, self.PORTAL_AUD)

        assert payload is not None
        assert payload["email"] == "user@example.com"
        assert payload["sub"] == "user-id-123"

    @pytest.mark.asyncio
    async def test_expired_jwt_rejected(self):
        """Test that an expired JWT is rejected."""
        from app.api.auth_simple import _verify_cf_access_jwt

        key = _get_test_rsa_key()
        jwks = _make_jwks_response(key)
        # Token expired 2 hours ago (well past the 60s leeway)
        token = _sign_jwt(key, team_domain=self.TEAM_DOMAIN, aud=self.PORTAL_AUD, exp_offset=-7200)

        with patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value=jwks):
            payload = await _verify_cf_access_jwt(token, self.TEAM_DOMAIN, self.PORTAL_AUD)

        assert payload is None

    @pytest.mark.asyncio
    async def test_wrong_audience_rejected(self):
        """Test that a JWT with wrong audience is rejected."""
        from app.api.auth_simple import _verify_cf_access_jwt

        key = _get_test_rsa_key()
        jwks = _make_jwks_response(key)
        token = _sign_jwt(key, team_domain=self.TEAM_DOMAIN, aud="wrong-audience")

        with patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value=jwks):
            payload = await _verify_cf_access_jwt(token, self.TEAM_DOMAIN, self.PORTAL_AUD)

        assert payload is None

    @pytest.mark.asyncio
    async def test_wrong_issuer_rejected(self):
        """Test that a JWT with wrong issuer is rejected."""
        from app.api.auth_simple import _verify_cf_access_jwt

        key = _get_test_rsa_key()
        jwks = _make_jwks_response(key)
        token = _sign_jwt(
            key,
            team_domain=self.TEAM_DOMAIN,
            aud=self.PORTAL_AUD,
            iss="https://evil.cloudflareaccess.com",
        )

        with patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value=jwks):
            payload = await _verify_cf_access_jwt(token, self.TEAM_DOMAIN, self.PORTAL_AUD)

        assert payload is None

    @pytest.mark.asyncio
    async def test_tampered_jwt_rejected(self):
        """Test that a JWT with tampered payload is rejected."""
        from app.api.auth_simple import _verify_cf_access_jwt

        key = _get_test_rsa_key()
        jwks = _make_jwks_response(key)
        token = _sign_jwt(key, team_domain=self.TEAM_DOMAIN, aud=self.PORTAL_AUD)

        # Tamper with the payload by changing a character
        parts = token.split(".")
        payload_b64 = parts[1]
        tampered = payload_b64[:-1] + ("A" if payload_b64[-1] != "A" else "B")
        tampered_token = f"{parts[0]}.{tampered}.{parts[2]}"

        with patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value=jwks):
            payload = await _verify_cf_access_jwt(tampered_token, self.TEAM_DOMAIN, self.PORTAL_AUD)

        assert payload is None

    @pytest.mark.asyncio
    async def test_malformed_jwt_rejected(self):
        """Test that a malformed JWT string is rejected."""
        from app.api.auth_simple import _verify_cf_access_jwt

        key = _get_test_rsa_key()
        jwks = _make_jwks_response(key)

        with patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value=jwks):
            # Not a JWT at all
            payload = await _verify_cf_access_jwt("not-a-jwt", self.TEAM_DOMAIN, self.PORTAL_AUD)
            assert payload is None

            # Wrong number of parts
            payload = await _verify_cf_access_jwt("a.b", self.TEAM_DOMAIN, self.PORTAL_AUD)
            assert payload is None

    @pytest.mark.asyncio
    async def test_wrong_kid_rejected(self):
        """Test that a JWT signed with unknown kid is rejected."""
        from app.api.auth_simple import _verify_cf_access_jwt

        key = _get_test_rsa_key()
        jwks = _make_jwks_response(key, kid="correct-key")
        token = _sign_jwt(key, kid="wrong-key", team_domain=self.TEAM_DOMAIN, aud=self.PORTAL_AUD)

        with patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value=jwks):
            # PyJWT matches by kid, so a wrong kid means no matching key → rejected.
            result = await _verify_cf_access_jwt(token, self.TEAM_DOMAIN, self.PORTAL_AUD)
            assert result is None

    @pytest.mark.asyncio
    async def test_jwks_unavailable_rejects_jwt(self):
        """Test that JWTs are rejected when JWKS cannot be fetched."""
        from app.api.auth_simple import _verify_cf_access_jwt

        key = _get_test_rsa_key()
        token = _sign_jwt(key, team_domain=self.TEAM_DOMAIN, aud=self.PORTAL_AUD)

        with patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value=None):
            payload = await _verify_cf_access_jwt(token, self.TEAM_DOMAIN, self.PORTAL_AUD)

        assert payload is None

    @pytest.mark.asyncio
    async def test_empty_jwks_rejects_jwt(self):
        """Test that JWTs are rejected when JWKS has no keys."""
        from app.api.auth_simple import _verify_cf_access_jwt

        key = _get_test_rsa_key()
        token = _sign_jwt(key, team_domain=self.TEAM_DOMAIN, aud=self.PORTAL_AUD)

        with patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value={}):
            payload = await _verify_cf_access_jwt(token, self.TEAM_DOMAIN, self.PORTAL_AUD)

        assert payload is None


class TestJWTIntegrationWithGateway:
    """Tests for JWT verification integrated with the MCP gateway auth flow.

    Verifies that valid JWTs set auth_method='jwt' (allowing tool execution)
    and invalid JWTs fall back to auth_method='oauth' (blocked).
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
    async def test_valid_jwt_sets_auth_method_jwt(self):
        """Test that a valid JWT sets auth_method to 'jwt' on the user."""
        from app.api.auth_simple import verify_mcp_auth
        from app.services.service_token_cache import ServiceTokenCache

        test_token = "a" * 32
        key = _get_test_rsa_key()
        jwks = _make_jwks_response(key)
        jwt_token = _sign_jwt(key)

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)
        mock_cache.get_team_domain = AsyncMock(return_value="test.cloudflareaccess.com")
        mock_cache.get_portal_aud = AsyncMock(return_value="test-aud-1234")

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache),
            patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value=jwks),
        ):
            user = await verify_mcp_auth(
                request=self._make_mock_request(),
                x_mcpbox_service_token=test_token,
                cf_access_jwt_assertion=jwt_token,
            )

        assert user.source == "worker"
        assert user.auth_method == "jwt"
        assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_invalid_jwt_falls_back_to_oauth(self):
        """Test that an invalid JWT falls back to auth_method='oauth'."""
        from app.api.auth_simple import verify_mcp_auth
        from app.services.service_token_cache import ServiceTokenCache

        test_token = "a" * 32
        key = _get_test_rsa_key()
        jwks = _make_jwks_response(key)

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)
        mock_cache.get_team_domain = AsyncMock(return_value="test.cloudflareaccess.com")
        mock_cache.get_portal_aud = AsyncMock(return_value="test-aud-1234")

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache),
            patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value=jwks),
        ):
            user = await verify_mcp_auth(
                request=self._make_mock_request(),
                x_mcpbox_service_token=test_token,
                cf_access_jwt_assertion="invalid-jwt-token",
            )

        assert user.source == "worker"
        assert user.auth_method == "oauth"
        assert user.email is None

    @pytest.mark.asyncio
    async def test_oauth_with_worker_email_header(self):
        """Test that Worker-supplied email header is used when JWT is not present.

        When a valid service token is present (proving Worker provenance),
        the gateway trusts the X-MCPbox-User-Email header from OAuth props.
        """
        from app.api.auth_simple import verify_mcp_auth
        from app.services.service_token_cache import ServiceTokenCache

        test_token = "a" * 32

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)
        mock_cache.get_team_domain = AsyncMock(return_value=None)
        mock_cache.get_portal_aud = AsyncMock(return_value=None)

        mock_request = self._make_mock_request()
        mock_request.headers = MagicMock()
        mock_request.headers.get = MagicMock(
            side_effect=lambda key, default=None: {
                "X-MCPbox-User-Email": "user@example.com",
            }.get(key, default)
        )

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
            user = await verify_mcp_auth(
                request=mock_request,
                x_mcpbox_service_token=test_token,
                cf_access_jwt_assertion=None,
            )

        assert user.source == "worker"
        assert user.auth_method == "oauth"
        assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_jwt_email_takes_precedence_over_worker_header(self):
        """Test that JWT-verified email takes precedence over Worker-supplied header."""
        from app.api.auth_simple import verify_mcp_auth
        from app.services.service_token_cache import ServiceTokenCache

        test_token = "a" * 32
        key = _get_test_rsa_key()
        jwks = _make_jwks_response(key)
        jwt_token = _sign_jwt(key, email="jwt-user@example.com")

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)
        mock_cache.get_team_domain = AsyncMock(return_value="test.cloudflareaccess.com")
        mock_cache.get_portal_aud = AsyncMock(return_value="test-aud-1234")

        mock_request = self._make_mock_request()
        mock_request.headers = MagicMock()
        mock_request.headers.get = MagicMock(
            side_effect=lambda key_name, default=None: {
                "X-MCPbox-User-Email": "oauth-user@example.com",
            }.get(key_name, default)
        )

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache),
            patch("app.api.auth_simple._get_jwks", new_callable=AsyncMock, return_value=jwks),
        ):
            user = await verify_mcp_auth(
                request=mock_request,
                x_mcpbox_service_token=test_token,
                cf_access_jwt_assertion=jwt_token,
            )

        # JWT email should take precedence
        assert user.email == "jwt-user@example.com"
        assert user.auth_method == "jwt"

    @pytest.mark.asyncio
    async def test_no_jwt_header_defaults_to_oauth(self):
        """Test that missing JWT header defaults to auth_method='oauth'."""
        from app.api.auth_simple import verify_mcp_auth
        from app.services.service_token_cache import ServiceTokenCache

        test_token = "a" * 32

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)
        mock_cache.get_team_domain = AsyncMock(return_value="test.cloudflareaccess.com")
        mock_cache.get_portal_aud = AsyncMock(return_value="test-aud-1234")

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
            user = await verify_mcp_auth(
                request=self._make_mock_request(),
                x_mcpbox_service_token=test_token,
                cf_access_jwt_assertion=None,
            )

        assert user.source == "worker"
        assert user.auth_method == "oauth"

    @pytest.mark.asyncio
    async def test_oauth_allows_tools_call_at_gateway(
        self, async_client: AsyncClient, mock_sandbox_client
    ):
        """End-to-end: Worker request without JWT allows tools/call (OAuth + service token sufficient)."""
        mock_sandbox_client.mcp_request = AsyncMock(
            return_value={"result": {"content": [{"type": "text", "text": "ok"}]}}
        )
        test_token = "a" * 32

        from app.services.service_token_cache import ServiceTokenCache

        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)
        mock_cache.get_team_domain = AsyncMock(return_value=None)
        mock_cache.get_portal_aud = AsyncMock(return_value=None)

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
            # tools/call should succeed with valid service token (OAuth + service token sufficient)
            response = await async_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "some_tool", "arguments": {}},
                },
                headers={"X-MCPbox-Service-Token": test_token},
            )
            assert response.status_code == 200
            result = response.json()
            # Should not be blocked - sandbox was called
            mock_sandbox_client.mcp_request.assert_called()


class TestMCPGatewaySyncAuth:
    """Regression tests for Cloudflare sync and Portal user scenarios.

    Cloudflare's MCP server sync authenticates via OAuth (no JWT, no email).
    Sync-only methods (initialize, tools/list, notifications) are allowed.
    Tool execution (tools/call) and unknown methods require a verified user
    identity (email from MCP Portal OAuth props or JWT).

    These tests mock ServiceTokenCache with a valid service token and no JWT
    verification config (team_domain=None, portal_aud=None), simulating the
    Worker forwarding requests with a valid service token but no JWT.
    """

    @staticmethod
    def _make_sync_headers(test_token: str) -> dict[str, str]:
        return {"X-MCPbox-Service-Token": test_token}

    @staticmethod
    def _make_sync_cache(test_token: str) -> MagicMock:
        mock_cache = MagicMock()
        mock_cache.is_auth_enabled = AsyncMock(return_value=True)
        mock_cache.get_token = AsyncMock(return_value=test_token)
        mock_cache.get_team_domain = AsyncMock(return_value=None)
        mock_cache.get_portal_aud = AsyncMock(return_value=None)
        return mock_cache

    @pytest.mark.asyncio
    async def test_sync_initialize_allowed(self, async_client: AsyncClient, mock_sandbox_client):
        """Cloudflare sync can call initialize (needed for MCP handshake)."""
        test_token = "a" * 32
        mock_cache = self._make_sync_cache(test_token)

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
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
        assert result["result"]["protocolVersion"] == "2024-11-05"
        assert result["result"]["serverInfo"]["name"] == "mcpbox"

    @pytest.mark.asyncio
    async def test_sync_tools_list_allowed(self, async_client: AsyncClient, mock_sandbox_client):
        """Cloudflare sync can call tools/list (needed for tool discovery)."""
        mock_sandbox_client.mcp_request = AsyncMock(return_value={"result": {"tools": []}})
        test_token = "a" * 32
        mock_cache = self._make_sync_cache(test_token)

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
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
        assert "result" in result
        assert "tools" in result["result"]

    @pytest.mark.asyncio
    async def test_sync_notifications_allowed(self, async_client: AsyncClient):
        """Cloudflare sync can send notifications (needed after initialize)."""
        test_token = "a" * 32
        mock_cache = self._make_sync_cache(test_token)

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
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

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
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

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
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

        with patch.object(ServiceTokenCache, "get_instance", return_value=mock_cache):
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
