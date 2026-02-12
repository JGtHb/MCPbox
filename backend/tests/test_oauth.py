"""Tests for OAuth 2.0 authorization code flow endpoints."""

import pytest
from httpx import AsyncClient


@pytest.fixture
async def test_server(async_client: AsyncClient, admin_headers):
    """Create a test server for OAuth tests."""
    response = await async_client.post(
        "/api/servers",
        json={"name": "OAuth Test Server"},
        headers=admin_headers,
    )
    return response.json()


@pytest.fixture
async def oauth_credential(async_client: AsyncClient, test_server, admin_headers):
    """Create an OAuth credential with authorization_code grant type."""
    response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "GITHUB_OAUTH",
            "description": "GitHub OAuth credential",
            "auth_type": "oauth2",
            "oauth_client_id": "test_client_id",
            "oauth_client_secret": "test_client_secret",
            "oauth_token_url": "https://github.com/login/oauth/access_token",
            "oauth_authorization_url": "https://github.com/login/oauth/authorize",
            "oauth_scopes": ["read:user", "user:email"],
            "oauth_grant_type": "authorization_code",
        },
        headers=admin_headers,
    )
    return response.json()


@pytest.fixture
async def client_credentials_credential(async_client: AsyncClient, test_server, admin_headers):
    """Create an OAuth credential with client_credentials grant type."""
    response = await async_client.post(
        f"/api/servers/{test_server['id']}/credentials",
        json={
            "name": "API_OAUTH",
            "auth_type": "oauth2",
            "oauth_client_id": "api_client_id",
            "oauth_client_secret": "api_client_secret",
            "oauth_token_url": "https://api.example.com/oauth/token",
            "oauth_grant_type": "client_credentials",
        },
        headers=admin_headers,
    )
    return response.json()


class TestOAuthProviders:
    """Tests for OAuth provider endpoints."""

    @pytest.mark.asyncio
    async def test_list_oauth_providers(self, async_client: AsyncClient, admin_headers):
        """Test listing OAuth provider presets."""
        response = await async_client.get("/api/oauth/providers", headers=admin_headers)
        assert response.status_code == 200
        providers = response.json()
        assert isinstance(providers, list)
        assert len(providers) > 0

        # Check that common providers are included
        provider_ids = [p["id"] for p in providers]
        assert "google" in provider_ids
        assert "github" in provider_ids
        assert "slack" in provider_ids

    @pytest.mark.asyncio
    async def test_get_oauth_provider(self, async_client: AsyncClient, admin_headers):
        """Test getting a specific OAuth provider."""
        response = await async_client.get("/api/oauth/providers/github", headers=admin_headers)
        assert response.status_code == 200
        provider = response.json()
        assert provider["id"] == "github"
        assert provider["name"] == "GitHub"
        assert "authorization_url" in provider
        assert "token_url" in provider
        assert "scopes" in provider

    @pytest.mark.asyncio
    async def test_get_oauth_provider_not_found(self, async_client: AsyncClient, admin_headers):
        """Test getting a non-existent OAuth provider."""
        response = await async_client.get("/api/oauth/providers/nonexistent", headers=admin_headers)
        assert response.status_code == 404


class TestOAuthCredentialCreation:
    """Tests for OAuth credential creation."""

    @pytest.mark.asyncio
    async def test_create_authorization_code_credential(
        self, async_client: AsyncClient, test_server, admin_headers
    ):
        """Test creating an OAuth credential with authorization_code grant."""
        response = await async_client.post(
            f"/api/servers/{test_server['id']}/credentials",
            json={
                "name": "GITHUB_AUTH",
                "auth_type": "oauth2",
                "oauth_client_id": "my_client_id",
                "oauth_client_secret": "my_client_secret",
                "oauth_token_url": "https://github.com/login/oauth/access_token",
                "oauth_authorization_url": "https://github.com/login/oauth/authorize",
                "oauth_scopes": ["read:user"],
                "oauth_grant_type": "authorization_code",
            },
            headers=admin_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["auth_type"] == "oauth2"
        assert data["oauth_grant_type"] == "authorization_code"
        assert data["oauth_authorization_url"] == "https://github.com/login/oauth/authorize"
        assert data["oauth_flow_pending"] is False
        assert data["has_access_token"] is False

    @pytest.mark.asyncio
    async def test_create_authorization_code_missing_auth_url(
        self, async_client: AsyncClient, test_server, admin_headers
    ):
        """Test that authorization_code grant requires authorization URL."""
        response = await async_client.post(
            f"/api/servers/{test_server['id']}/credentials",
            json={
                "name": "MISSING_AUTH_URL",
                "auth_type": "oauth2",
                "oauth_client_id": "my_client_id",
                "oauth_token_url": "https://example.com/oauth/token",
                "oauth_grant_type": "authorization_code",
                # Missing oauth_authorization_url
            },
            headers=admin_headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_client_credentials_credential(
        self, async_client: AsyncClient, test_server, admin_headers
    ):
        """Test creating an OAuth credential with client_credentials grant."""
        response = await async_client.post(
            f"/api/servers/{test_server['id']}/credentials",
            json={
                "name": "API_AUTH",
                "auth_type": "oauth2",
                "oauth_client_id": "api_client_id",
                "oauth_client_secret": "api_client_secret",
                "oauth_token_url": "https://api.example.com/oauth/token",
                "oauth_grant_type": "client_credentials",
            },
            headers=admin_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["oauth_grant_type"] == "client_credentials"
        assert data["oauth_authorization_url"] is None


class TestOAuthFlow:
    """Tests for OAuth authorization flow endpoints."""

    @pytest.mark.asyncio
    async def test_start_oauth_flow(
        self, async_client: AsyncClient, oauth_credential, admin_headers
    ):
        """Test starting OAuth authorization flow."""
        credential_id = oauth_credential["id"]
        response = await async_client.post(
            f"/api/oauth/credentials/{credential_id}/start", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "authorization_url" in data
        assert "state" in data
        assert data["credential_id"] == credential_id

        # Verify authorization URL contains expected parameters
        auth_url = data["authorization_url"]
        assert "client_id=test_client_id" in auth_url
        assert "response_type=code" in auth_url
        assert "state=" in auth_url
        assert "code_challenge=" in auth_url
        assert "code_challenge_method=S256" in auth_url

    @pytest.mark.asyncio
    async def test_start_oauth_flow_wrong_grant_type(
        self, async_client: AsyncClient, client_credentials_credential, admin_headers
    ):
        """Test that starting OAuth flow fails for client_credentials grant."""
        credential_id = client_credentials_credential["id"]
        response = await async_client.post(
            f"/api/oauth/credentials/{credential_id}/start", headers=admin_headers
        )
        assert response.status_code == 400
        assert "authorization_code" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_start_oauth_flow_not_found(self, async_client: AsyncClient, admin_headers):
        """Test starting OAuth flow for non-existent credential."""
        response = await async_client.post(
            "/api/oauth/credentials/00000000-0000-0000-0000-000000000000/start",
            headers=admin_headers,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_start_oauth_flow_non_oauth_credential(
        self, async_client: AsyncClient, test_server, admin_headers
    ):
        """Test that starting OAuth flow fails for non-OAuth credentials."""
        # Create a bearer token credential
        create_response = await async_client.post(
            f"/api/servers/{test_server['id']}/credentials",
            json={
                "name": "BEARER_TOKEN",
                "auth_type": "bearer",
                "value": "my_token",
            },
            headers=admin_headers,
        )
        credential_id = create_response.json()["id"]

        response = await async_client.post(
            f"/api/oauth/credentials/{credential_id}/start", headers=admin_headers
        )
        assert response.status_code == 400


class TestOAuthTokenStatus:
    """Tests for OAuth token status endpoint."""

    @pytest.mark.asyncio
    async def test_get_token_status_no_token(
        self, async_client: AsyncClient, oauth_credential, admin_headers
    ):
        """Test getting token status when no token is configured."""
        credential_id = oauth_credential["id"]
        response = await async_client.get(
            f"/api/oauth/credentials/{credential_id}/status", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["credential_id"] == credential_id
        assert data["has_access_token"] is False
        assert data["has_refresh_token"] is False
        assert data["is_expired"] is True
        assert data["flow_pending"] is False

    @pytest.mark.asyncio
    async def test_get_token_status_after_flow_start(
        self, async_client: AsyncClient, oauth_credential, admin_headers
    ):
        """Test token status shows flow pending after starting OAuth."""
        credential_id = oauth_credential["id"]

        # Start the flow
        await async_client.post(
            f"/api/oauth/credentials/{credential_id}/start", headers=admin_headers
        )

        # Check status
        response = await async_client.get(
            f"/api/oauth/credentials/{credential_id}/status", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["flow_pending"] is True

    @pytest.mark.asyncio
    async def test_get_token_status_not_found(self, async_client: AsyncClient, admin_headers):
        """Test getting token status for non-existent credential."""
        response = await async_client.get(
            "/api/oauth/credentials/00000000-0000-0000-0000-000000000000/status",
            headers=admin_headers,
        )
        assert response.status_code == 404


class TestOAuthTokenRefresh:
    """Tests for OAuth token refresh endpoint."""

    @pytest.mark.asyncio
    async def test_refresh_token_no_refresh_token(
        self, async_client: AsyncClient, oauth_credential, admin_headers
    ):
        """Test that refresh fails when no refresh token is available."""
        credential_id = oauth_credential["id"]
        response = await async_client.post(
            f"/api/oauth/credentials/{credential_id}/refresh", headers=admin_headers
        )
        assert response.status_code == 400
        assert "refresh token" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_refresh_token_not_found(self, async_client: AsyncClient, admin_headers):
        """Test refresh for non-existent credential."""
        response = await async_client.post(
            "/api/oauth/credentials/00000000-0000-0000-0000-000000000000/refresh",
            headers=admin_headers,
        )
        assert response.status_code == 404


class TestOAuthCallbackAPI:
    """Tests for OAuth callback API endpoint."""

    @pytest.mark.asyncio
    async def test_callback_invalid_state(self, async_client: AsyncClient, admin_headers):
        """Test callback with invalid state."""
        response = await async_client.post(
            "/api/oauth/callback",
            json={
                "code": "test_code",
                "state": "invalid_state",
            },
            headers=admin_headers,
        )
        assert response.status_code == 400
        assert "state" in response.json()["detail"].lower()


class TestOAuthCredentialResponse:
    """Tests for OAuth fields in credential responses."""

    @pytest.mark.asyncio
    async def test_credential_response_includes_oauth_fields(
        self, async_client: AsyncClient, oauth_credential, admin_headers
    ):
        """Test that credential response includes OAuth-specific fields."""
        credential_id = oauth_credential["id"]
        response = await async_client.get(
            f"/api/credentials/{credential_id}", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()

        # Check OAuth fields are present
        assert "oauth_grant_type" in data
        assert data["oauth_grant_type"] == "authorization_code"
        assert "oauth_authorization_url" in data
        assert data["oauth_authorization_url"] == "https://github.com/login/oauth/authorize"
        assert "oauth_flow_pending" in data
        assert data["oauth_flow_pending"] is False

    @pytest.mark.asyncio
    async def test_credential_response_flow_pending_after_start(
        self, async_client: AsyncClient, oauth_credential, admin_headers
    ):
        """Test that oauth_flow_pending is True after starting flow."""
        credential_id = oauth_credential["id"]

        # Start the OAuth flow
        await async_client.post(
            f"/api/oauth/credentials/{credential_id}/start", headers=admin_headers
        )

        # Get credential and check flow_pending
        response = await async_client.get(
            f"/api/credentials/{credential_id}", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["oauth_flow_pending"] is True
