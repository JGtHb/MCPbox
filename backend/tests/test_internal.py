"""Tests for internal service-to-service endpoints."""

import json

import pytest
from httpx import AsyncClient

from app.models.cloudflare_config import CloudflareConfig
from app.models.tunnel_configuration import TunnelConfiguration
from app.services.crypto import encrypt_to_base64

pytestmark = pytest.mark.asyncio

# The test sandbox API key is set to "0" * 32 in conftest.py
INTERNAL_AUTH_HEADER = {"Authorization": f"Bearer {'0' * 32}"}


@pytest.fixture
def tunnel_config_factory(db_session):
    """Factory for creating test TunnelConfiguration objects."""

    async def _create_config(
        name: str = "Test Config",
        tunnel_token: str = "test-tunnel-token-12345",
        is_active: bool = False,
    ) -> TunnelConfiguration:
        encrypted_token = (
            encrypt_to_base64(tunnel_token, aad="tunnel_token") if tunnel_token else None
        )
        config = TunnelConfiguration(
            name=name,
            tunnel_token=encrypted_token,
            is_active=is_active,
        )
        db_session.add(config)
        await db_session.flush()
        await db_session.refresh(config)
        return config

    return _create_config


class TestInternalAuth:
    """Tests for internal endpoint authentication."""

    async def test_returns_403_without_auth(self, async_client: AsyncClient):
        """Requests without Authorization header are rejected."""
        response = await async_client.get("/internal/active-tunnel-token")
        assert response.status_code == 403

    async def test_returns_403_with_wrong_token(self, async_client: AsyncClient):
        """Requests with wrong Bearer token are rejected."""
        response = await async_client.get(
            "/internal/active-tunnel-token",
            headers={"Authorization": "Bearer wrong-token-value-xxxxx"},
        )
        assert response.status_code == 403

    async def test_returns_403_with_non_bearer_auth(self, async_client: AsyncClient):
        """Requests with non-Bearer auth scheme are rejected."""
        response = await async_client.get(
            "/internal/active-tunnel-token",
            headers={"Authorization": f"Basic {'0' * 32}"},
        )
        assert response.status_code == 403

    async def test_all_internal_endpoints_require_auth(self, async_client: AsyncClient):
        """All internal endpoints reject unauthenticated requests."""
        endpoints = [
            "/internal/active-tunnel-token",
            "/internal/worker-deploy-config",
            "/internal/active-service-token",
        ]
        for endpoint in endpoints:
            response = await async_client.get(endpoint)
            assert response.status_code == 403, f"{endpoint} should require auth"


class TestGetActiveTunnelToken:
    """Tests for GET /internal/active-tunnel-token endpoint."""

    async def test_returns_token_when_active_config_exists(
        self, async_client: AsyncClient, tunnel_config_factory
    ):
        await tunnel_config_factory(name="Active", is_active=True, tunnel_token="my-secret-token")

        response = await async_client.get(
            "/internal/active-tunnel-token", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token"] == "my-secret-token"

    async def test_returns_null_when_no_active_config(
        self, async_client: AsyncClient, tunnel_config_factory
    ):
        await tunnel_config_factory(name="Inactive", is_active=False)

        response = await async_client.get(
            "/internal/active-tunnel-token", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token"] is None
        assert "No active" in data["error"]

    async def test_returns_null_when_no_configs_at_all(self, async_client: AsyncClient):
        response = await async_client.get(
            "/internal/active-tunnel-token", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token"] is None

    async def test_returns_null_when_active_config_has_no_token(
        self, async_client: AsyncClient, tunnel_config_factory
    ):
        await tunnel_config_factory(name="No Token", is_active=True, tunnel_token=None)

        response = await async_client.get(
            "/internal/active-tunnel-token", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token"] is None

    async def test_no_jwt_auth_required(self, async_client: AsyncClient, tunnel_config_factory):
        """Internal endpoint does not require JWT admin auth (uses its own auth)."""
        await tunnel_config_factory(is_active=True)

        response = await async_client.get(
            "/internal/active-tunnel-token", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200


@pytest.fixture
def cloudflare_config_factory(db_session):
    """Factory for creating test CloudflareConfig objects."""

    async def _create_config(
        status: str = "active",
        vpc_service_id: str | None = "019c3973-f7c8-7ce0-8af8-00b132f54ff9",
        worker_name: str | None = "mcpbox-proxy",
        team_domain: str | None = "myteam.cloudflareaccess.com",
        has_service_token: bool = True,
        completed_step: int = 5,
        kv_namespace_id: str | None = None,
        access_policy_type: str | None = None,
        access_policy_emails: list[str] | None = None,
        access_policy_email_domain: str | None = None,
    ) -> CloudflareConfig:
        config = CloudflareConfig(
            encrypted_api_token=encrypt_to_base64("fake-api-token", aad="cloudflare_api_token"),
            account_id="test-account-id",
            account_name="Test Account",
            status=status,
            vpc_service_id=vpc_service_id,
            worker_name=worker_name,
            team_domain=team_domain,
            encrypted_service_token=encrypt_to_base64("svc-token", aad="service_token")
            if has_service_token
            else None,
            completed_step=completed_step,
            kv_namespace_id=kv_namespace_id,
            access_policy_type=access_policy_type,
            access_policy_emails=(
                json.dumps(access_policy_emails) if access_policy_emails else None
            ),
            access_policy_email_domain=access_policy_email_domain,
        )
        db_session.add(config)
        await db_session.flush()
        await db_session.refresh(config)
        return config

    return _create_config


class TestGetWorkerDeployConfig:
    """Tests for GET /internal/worker-deploy-config endpoint."""

    async def test_returns_config_when_active(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        await cloudflare_config_factory(kv_namespace_id="kv-test-123")

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["vpc_service_id"] == "019c3973-f7c8-7ce0-8af8-00b132f54ff9"
        assert data["worker_name"] == "mcpbox-proxy"
        assert data["has_service_token"] is True
        assert data["kv_namespace_id"] == "kv-test-123"

    async def test_returns_error_when_no_active_config(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        await cloudflare_config_factory(status="pending")

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "No active" in data["error"]

    async def test_returns_error_when_no_vpc_service(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        await cloudflare_config_factory(vpc_service_id=None, completed_step=2)

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "VPC" in data["error"]

    async def test_returns_error_when_no_configs(self, async_client: AsyncClient):
        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data

    async def test_defaults_worker_name(self, async_client: AsyncClient, cloudflare_config_factory):
        await cloudflare_config_factory(worker_name=None)

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["worker_name"] == "mcpbox-proxy"

    async def test_no_jwt_auth_required(self, async_client: AsyncClient, cloudflare_config_factory):
        """Internal endpoint does not require JWT admin auth (uses its own auth)."""
        await cloudflare_config_factory()

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200


class TestGetActiveServiceToken:
    """Tests for GET /internal/active-service-token endpoint."""

    async def test_returns_token_when_active_config_with_token(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        await cloudflare_config_factory(has_service_token=True)

        response = await async_client.get(
            "/internal/active-service-token", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token"] is not None
        assert data["token"] == "svc-token"

    async def test_returns_null_when_no_active_config(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        await cloudflare_config_factory(status="pending")

        response = await async_client.get(
            "/internal/active-service-token", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token"] is None
        assert "error" in data

    async def test_returns_null_when_no_service_token(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        await cloudflare_config_factory(has_service_token=False)

        response = await async_client.get(
            "/internal/active-service-token", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token"] is None
        assert "error" in data

    async def test_returns_null_when_no_configs(self, async_client: AsyncClient):
        response = await async_client.get(
            "/internal/active-service-token", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token"] is None

    async def test_no_jwt_auth_required(self, async_client: AsyncClient, cloudflare_config_factory):
        """Internal endpoint does not require JWT admin auth (uses its own auth)."""
        await cloudflare_config_factory()

        response = await async_client.get(
            "/internal/active-service-token", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200


class TestWorkerDeployConfigOidc:
    """Tests for OIDC credential fields in GET /internal/worker-deploy-config."""

    async def test_returns_oidc_urls_when_credentials_configured(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        """When OIDC credentials are set, endpoint returns OIDC endpoint URLs."""
        config = await cloudflare_config_factory()
        # Set OIDC credentials on the config
        config.encrypted_access_client_id = encrypt_to_base64(
            "test-client-id", aad="access_client_id"
        )
        config.encrypted_access_client_secret = encrypt_to_base64(
            "test-client-secret", aad="access_client_secret"
        )

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["access_client_id"] == "test-client-id"
        assert data["access_client_secret"] == "test-client-secret"
        assert "token" in data["access_token_url"]
        assert "authorize" in data["access_authorization_url"]
        assert "certs" in data["access_jwks_url"]

    async def test_returns_empty_oidc_when_not_configured(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        """When no OIDC credentials, endpoint returns empty strings."""
        await cloudflare_config_factory()

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["access_client_id"] == ""
        assert data["access_client_secret"] == ""
        assert data["access_token_url"] == ""
        assert data["access_authorization_url"] == ""
        assert data["access_jwks_url"] == ""
