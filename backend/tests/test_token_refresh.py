"""Tests for the background token refresh service."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.crypto import encrypt
from app.services.token_refresh import TokenRefreshService


@pytest.fixture
async def oauth_credential_with_expiring_token(
    async_client, credential_factory, server_factory, db_session, admin_headers
):
    """Create an OAuth credential with an expiring access token."""

    server = await server_factory(name="token_refresh_test_server")

    # Create credential via API for proper initialization
    response = await async_client.post(
        f"/api/servers/{server.id}/credentials",
        json={
            "name": "EXPIRING_OAUTH",
            "auth_type": "oauth2",
            "oauth_client_id": "test_client_id",
            "oauth_client_secret": "test_client_secret",
            "oauth_token_url": "https://example.com/oauth/token",
            "oauth_grant_type": "client_credentials",
        },
        headers=admin_headers,
    )
    return response.json(), server, db_session


class TestTokenRefreshService:
    """Tests for TokenRefreshService."""

    @pytest.mark.asyncio
    async def test_singleton_pattern(self):
        """Test that get_instance returns the same instance."""
        instance1 = TokenRefreshService.get_instance()
        instance2 = TokenRefreshService.get_instance()
        assert instance1 is instance2

    @pytest.mark.asyncio
    async def test_start_stop_service(self):
        """Test starting and stopping the service."""
        service = TokenRefreshService()

        # Start service
        await service.start()
        assert service._running is True
        assert TokenRefreshService._task is not None

        # Stop service
        await service.stop()
        assert service._running is False

    @pytest.mark.asyncio
    async def test_refresh_expiring_tokens_no_credentials(self, db_session):
        """Test refresh loop when no credentials need refreshing."""
        service = TokenRefreshService()

        # Should complete without errors
        await service._refresh_expiring_tokens()

    @pytest.mark.asyncio
    async def test_refresh_expiring_tokens_with_mock(self, db_session):
        """Test refresh loop with mocked credentials."""

        service = TokenRefreshService()

        # Mock the OAuthService.refresh_token to avoid actual HTTP calls
        with patch("app.services.token_refresh.OAuthService") as mock_oauth_class:
            mock_oauth_instance = MagicMock()
            mock_oauth_instance.refresh_token = AsyncMock(
                return_value={
                    "access_token_refreshed": True,
                    "expires_at": datetime.now(UTC) + timedelta(hours=1),
                }
            )
            mock_oauth_class.return_value = mock_oauth_instance

            # Run refresh (should handle empty results gracefully)
            await service._refresh_expiring_tokens()

    @pytest.mark.asyncio
    async def test_refresh_single_credential_not_found(self, db_session):
        """Test refreshing a non-existent credential."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_session():
            yield db_session

        service = TokenRefreshService()
        with patch("app.services.token_refresh.async_session_maker", mock_session):
            result = await service.refresh_single_credential("00000000-0000-0000-0000-000000000000")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_refresh_single_credential_wrong_type(
        self, async_client, server_factory, db_session, admin_headers
    ):
        """Test refreshing a non-OAuth credential."""
        server = await server_factory(name="wrong_type_test")

        # Create a bearer token credential (not OAuth)
        response = await async_client.post(
            f"/api/servers/{server.id}/credentials",
            json={
                "name": "BEARER_TOKEN",
                "auth_type": "bearer",
                "value": "test_token",
            },
            headers=admin_headers,
        )
        credential_id = response.json()["id"]

        # Create a context manager that yields the test session
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_session():
            yield db_session

        service = TokenRefreshService()
        with patch("app.services.token_refresh.async_session_maker", mock_session):
            result = await service.refresh_single_credential(credential_id)
        assert result["success"] is False
        assert "oauth2" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_refresh_single_credential_no_refresh_token(
        self, oauth_credential_with_expiring_token
    ):
        """Test refreshing a credential without a refresh token."""
        credential_data, server, db_session = oauth_credential_with_expiring_token
        credential_id = credential_data["id"]

        # Create a context manager that yields the test session
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_session():
            yield db_session

        service = TokenRefreshService()
        with patch("app.services.token_refresh.async_session_maker", mock_session):
            result = await service.refresh_single_credential(credential_id)
        assert result["success"] is False
        assert "refresh token" in result["error"].lower()


class TestTokenRefreshIntegration:
    """Integration tests for token refresh with real HTTP mocking."""

    @pytest.mark.asyncio
    async def test_refresh_with_mocked_provider(
        self, async_client, server_factory, db_session, admin_headers
    ):
        """Test actual token refresh with mocked OAuth provider response."""
        from contextlib import asynccontextmanager
        from uuid import UUID

        from sqlalchemy import select

        from app.models.credential import Credential

        server = await server_factory(name="refresh_integration_test")

        # Create OAuth credential via API
        response = await async_client.post(
            f"/api/servers/{server.id}/credentials",
            json={
                "name": "INTEGRATION_OAUTH",
                "auth_type": "oauth2",
                "oauth_client_id": "test_client",
                "oauth_client_secret": "test_secret",
                "oauth_token_url": "https://example.com/oauth/token",
                "oauth_grant_type": "client_credentials",
            },
            headers=admin_headers,
        )
        credential_id = response.json()["id"]

        # Manually set up the credential with expiring token and refresh token
        # (simulating a credential that completed OAuth flow)
        query = select(Credential).where(Credential.id == UUID(credential_id))
        result = await db_session.execute(query)
        credential = result.scalar_one()

        # Set expiring access token and refresh token
        credential.encrypted_access_token = encrypt("old_access_token")
        credential.encrypted_refresh_token = encrypt("valid_refresh_token")
        credential.access_token_expires_at = datetime.now(UTC) - timedelta(minutes=5)
        await db_session.flush()
        await db_session.commit()

        # Create a context manager that yields the test session
        @asynccontextmanager
        async def mock_session():
            yield db_session

        # Mock the HTTP call to the OAuth provider
        service = TokenRefreshService()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
        }

        with (
            patch("app.services.token_refresh.async_session_maker", mock_session),
            patch("httpx.AsyncClient") as mock_client_class,
        ):
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client_instance

            result = await service.refresh_single_credential(credential_id)

            assert result["success"] is True
            assert result["expires_at"] is not None
