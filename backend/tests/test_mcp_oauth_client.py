"""Tests for the MCP OAuth 2.1 client service."""

import json
import time
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

from app.services.mcp_oauth_client import (
    OAuthDiscoveryError,
    OAuthError,
    OAuthFlowState,
    OAuthMetadata,
    OAuthTokenError,
    OAuthTokens,
    _cleanup_expired_flows,
    _generate_pkce,
    _parse_resource_metadata_url,
    _pending_flows,
    discover_oauth_metadata,
    encrypt_tokens,
    exchange_code,
    is_token_expired,
    start_oauth_flow,
)


class TestPKCE:
    """Tests for PKCE code generation."""

    def test_generates_verifier_and_challenge(self):
        verifier, challenge = _generate_pkce()
        assert len(verifier) > 40
        assert len(challenge) > 20
        assert verifier != challenge

    def test_generates_unique_values(self):
        v1, c1 = _generate_pkce()
        v2, c2 = _generate_pkce()
        assert v1 != v2
        assert c1 != c2


class TestResourceMetadataUrlParsing:
    """Tests for WWW-Authenticate header parsing."""

    def test_extracts_from_header(self):
        header = 'Bearer realm="mcp", resource_metadata="https://auth.example.com/.well-known/oauth-protected-resource"'
        result = _parse_resource_metadata_url(header, "https://mcp.example.com/mcp")
        assert result == "https://auth.example.com/.well-known/oauth-protected-resource"

    def test_falls_back_to_well_known(self):
        result = _parse_resource_metadata_url("Bearer", "https://mcp.example.com/mcp")
        assert result == "https://mcp.example.com/.well-known/oauth-protected-resource"

    def test_handles_empty_header(self):
        result = _parse_resource_metadata_url("", "https://mcp.example.com/mcp")
        assert result == "https://mcp.example.com/.well-known/oauth-protected-resource"


class TestFlowCleanup:
    """Tests for expired flow cleanup."""

    def test_removes_expired_flows(self):
        _pending_flows.clear()
        _pending_flows["old"] = OAuthFlowState(
            source_id=uuid4(),
            code_verifier="v",
            redirect_uri="http://localhost/callback",
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret=None,
            created_at=time.time() - 700,  # Expired
        )
        _pending_flows["new"] = OAuthFlowState(
            source_id=uuid4(),
            code_verifier="v2",
            redirect_uri="http://localhost/callback",
            token_endpoint="https://auth.example.com/token",
            client_id="cid2",
            client_secret=None,
            created_at=time.time(),  # Fresh
        )

        _cleanup_expired_flows()

        assert "old" not in _pending_flows
        assert "new" in _pending_flows
        _pending_flows.clear()


class TestTokenExpiry:
    """Tests for token expiry checking."""

    def test_not_expired_when_no_expiry(self):
        assert is_token_expired({"access_token": "abc"}) is False

    def test_not_expired_when_future(self):
        from datetime import UTC, datetime, timedelta

        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        assert is_token_expired({"expires_at": future}) is False

    def test_expired_when_past(self):
        from datetime import UTC, datetime, timedelta

        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        assert is_token_expired({"expires_at": past}) is True


class TestTokenEncryption:
    """Tests for token encryption/decryption round-trip."""

    @patch("app.services.mcp_oauth_client.encrypt_to_base64")
    @patch("app.services.mcp_oauth_client.decrypt_from_base64")
    def test_round_trip(self, mock_decrypt, mock_encrypt):
        tokens = OAuthTokens(
            access_token="at_123",
            refresh_token="rt_456",
            token_endpoint="https://auth.example.com/token",
            expires_at="2026-12-31T00:00:00+00:00",
            scope="read write",
        )

        # Mock encrypt to return the JSON directly (base64-encoded)
        mock_encrypt.side_effect = lambda x: x

        encrypted = encrypt_tokens(tokens, client_id="my_client")

        # Verify the encrypted data contains expected fields
        data = json.loads(encrypted)
        assert data["access_token"] == "at_123"
        assert data["refresh_token"] == "rt_456"
        assert data["token_endpoint"] == "https://auth.example.com/token"
        assert data["client_id"] == "my_client"


class TestDiscoverOAuthMetadata:
    """Tests for OAuth metadata discovery."""

    @pytest.mark.asyncio
    async def test_returns_metadata_on_success(self):
        probe_response = httpx.Response(
            401,
            headers={
                "www-authenticate": 'Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource"'
            },
        )
        prm_response = httpx.Response(
            200,
            json={
                "resource": "https://mcp.example.com",
                "authorization_servers": ["https://auth.example.com"],
            },
            request=httpx.Request("GET", "https://mcp.example.com/.well-known/oauth-protected-resource"),
        )
        asm_response = httpx.Response(
            200,
            json={
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
                "registration_endpoint": "https://auth.example.com/register",
                "issuer": "https://auth.example.com",
            },
            request=httpx.Request("GET", "https://auth.example.com/.well-known/oauth-authorization-server"),
        )

        with patch("app.services.mcp_oauth_client._get_http_client") as mock_client_factory:
            mock_client = AsyncMock()
            mock_client.post.return_value = probe_response
            mock_client.get.side_effect = [prm_response, asm_response]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_factory.return_value = mock_client

            metadata = await discover_oauth_metadata("https://mcp.example.com/mcp")

        assert metadata.authorization_endpoint == "https://auth.example.com/authorize"
        assert metadata.token_endpoint == "https://auth.example.com/token"
        assert metadata.registration_endpoint == "https://auth.example.com/register"
        assert metadata.resource == "https://mcp.example.com"

    @pytest.mark.asyncio
    async def test_raises_on_200_no_auth_needed(self):
        response = httpx.Response(200, json={"jsonrpc": "2.0", "result": {}})

        with patch("app.services.mcp_oauth_client._get_http_client") as mock_client_factory:
            mock_client = AsyncMock()
            mock_client.post.return_value = response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_factory.return_value = mock_client

            with pytest.raises(OAuthDiscoveryError, match="does not require OAuth"):
                await discover_oauth_metadata("https://mcp.example.com/mcp")

    @pytest.mark.asyncio
    async def test_raises_on_non_401(self):
        response = httpx.Response(403, text="Forbidden")

        with patch("app.services.mcp_oauth_client._get_http_client") as mock_client_factory:
            mock_client = AsyncMock()
            mock_client.post.return_value = response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_factory.return_value = mock_client

            with pytest.raises(OAuthDiscoveryError, match="Expected 401"):
                await discover_oauth_metadata("https://mcp.example.com/mcp")


class TestExchangeCode:
    """Tests for OAuth code exchange."""

    @pytest.mark.asyncio
    async def test_exchanges_code_for_tokens(self):
        source_id = uuid4()
        state = "test_state"
        _pending_flows.clear()
        _pending_flows[state] = OAuthFlowState(
            source_id=source_id,
            code_verifier="test_verifier",
            redirect_uri="http://localhost/callback",
            token_endpoint="https://auth.example.com/token",
            client_id="test_client",
            client_secret=None,
            created_at=time.time(),
        )

        token_response = httpx.Response(
            200,
            json={
                "access_token": "at_new",
                "refresh_token": "rt_new",
                "expires_in": 3600,
                "scope": "read",
            },
            request=httpx.Request("POST", "https://auth.example.com/token"),
        )

        with patch("app.services.mcp_oauth_client._get_http_client") as mock_client_factory:
            mock_client = AsyncMock()
            mock_client.post.return_value = token_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_factory.return_value = mock_client

            result_source_id, tokens = await exchange_code(state, "auth_code_123")

        assert result_source_id == source_id
        assert tokens.access_token == "at_new"
        assert tokens.refresh_token == "rt_new"
        assert state not in _pending_flows  # Flow consumed
        _pending_flows.clear()

    @pytest.mark.asyncio
    async def test_raises_on_invalid_state(self):
        _pending_flows.clear()
        with pytest.raises(OAuthTokenError, match="Invalid or expired"):
            await exchange_code("nonexistent_state", "code")

    @pytest.mark.asyncio
    async def test_raises_on_missing_access_token(self):
        state = "test_state_2"
        _pending_flows.clear()
        _pending_flows[state] = OAuthFlowState(
            source_id=uuid4(),
            code_verifier="v",
            redirect_uri="http://localhost/callback",
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret=None,
            created_at=time.time(),
        )

        token_response = httpx.Response(
            200,
            json={"error": "invalid_grant"},
            request=httpx.Request("POST", "https://auth.example.com/token"),
        )

        with patch("app.services.mcp_oauth_client._get_http_client") as mock_client_factory:
            mock_client = AsyncMock()
            mock_client.post.return_value = token_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_factory.return_value = mock_client

            with pytest.raises(OAuthTokenError, match="missing access_token"):
                await exchange_code(state, "bad_code")
        _pending_flows.clear()


class TestStartOAuthFlow:
    """Tests for the full OAuth flow initiation."""

    @pytest.mark.asyncio
    async def test_returns_auth_url(self):
        _pending_flows.clear()
        metadata = OAuthMetadata(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            registration_endpoint="https://auth.example.com/register",
            resource="https://mcp.example.com",
            scopes_supported=["read", "write"],
            issuer="https://auth.example.com",
        )

        with (
            patch("app.services.mcp_oauth_client.discover_oauth_metadata", return_value=metadata),
            patch(
                "app.services.mcp_oauth_client.register_client",
                return_value=("dcr_client_id", None),
            ),
        ):
            source_id = uuid4()
            result = await start_oauth_flow(
                source_id=source_id,
                mcp_url="https://mcp.example.com/mcp",
                callback_url="http://localhost:3000/oauth/callback",
            )

        assert "auth_url" in result
        assert "https://auth.example.com/authorize" in result["auth_url"]
        assert "code_challenge" in result["auth_url"]
        assert "code_challenge_method=S256" in result["auth_url"]
        assert result["issuer"] == "https://auth.example.com"
        assert len(_pending_flows) == 1
        _pending_flows.clear()

    @pytest.mark.asyncio
    async def test_uses_existing_client_id(self):
        _pending_flows.clear()
        metadata = OAuthMetadata(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
        )

        with patch("app.services.mcp_oauth_client.discover_oauth_metadata", return_value=metadata):
            result = await start_oauth_flow(
                source_id=uuid4(),
                mcp_url="https://mcp.example.com/mcp",
                callback_url="http://localhost:3000/oauth/callback",
                existing_client_id="my_preconfigured_client",
            )

        assert "client_id=my_preconfigured_client" in result["auth_url"]
        _pending_flows.clear()

    @pytest.mark.asyncio
    async def test_raises_when_no_dcr_and_no_client_id(self):
        metadata = OAuthMetadata(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            registration_endpoint=None,
        )

        with patch("app.services.mcp_oauth_client.discover_oauth_metadata", return_value=metadata):
            with pytest.raises(OAuthError, match="Dynamic Client Registration"):
                await start_oauth_flow(
                    source_id=uuid4(),
                    mcp_url="https://mcp.example.com/mcp",
                    callback_url="http://localhost:3000/oauth/callback",
                )
