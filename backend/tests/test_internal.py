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
        encrypted_token = encrypt_to_base64(tunnel_token) if tunnel_token else None
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
        mcp_portal_aud: str | None = "abc123def456",
        mcp_portal_hostname: str | None = None,
        has_service_token: bool = True,
        completed_step: int = 7,
        kv_namespace_id: str | None = None,
        access_policy_type: str | None = None,
        access_policy_emails: list[str] | None = None,
        access_policy_email_domain: str | None = None,
    ) -> CloudflareConfig:
        config = CloudflareConfig(
            encrypted_api_token=encrypt_to_base64("fake-api-token"),
            account_id="test-account-id",
            account_name="Test Account",
            status=status,
            vpc_service_id=vpc_service_id,
            worker_name=worker_name,
            team_domain=team_domain,
            mcp_portal_aud=mcp_portal_aud,
            mcp_portal_hostname=mcp_portal_hostname,
            encrypted_service_token=encrypt_to_base64("svc-token") if has_service_token else None,
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
        assert data["team_domain"] == "myteam.cloudflareaccess.com"
        assert data["mcp_portal_aud"] == "abc123def456"
        assert data["mcp_portal_hostname"] is None  # not set in factory by default
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

    async def test_returns_mcp_portal_hostname_when_set(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        await cloudflare_config_factory(mcp_portal_hostname="mcp.example.com")

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mcp_portal_hostname"] == "mcp.example.com"

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


class TestWorkerDeployConfigAccessPolicy:
    """Tests for access policy fields in GET /internal/worker-deploy-config."""

    async def test_returns_allowed_emails_when_configured(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        await cloudflare_config_factory(
            access_policy_type="emails",
            access_policy_emails=["user@example.com", "admin@example.com"],
        )

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["allowed_emails"] == "user@example.com,admin@example.com"
        assert data["allowed_email_domain"] == ""

    async def test_returns_allowed_email_domain_when_configured(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        await cloudflare_config_factory(
            access_policy_type="email_domain",
            access_policy_email_domain="example.com",
        )

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["allowed_emails"] == ""
        assert data["allowed_email_domain"] == "example.com"

    async def test_returns_empty_when_everyone_policy(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        await cloudflare_config_factory(access_policy_type="everyone")

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["allowed_emails"] == ""
        assert data["allowed_email_domain"] == ""

    async def test_returns_empty_when_no_policy_configured(
        self, async_client: AsyncClient, cloudflare_config_factory
    ):
        await cloudflare_config_factory()

        response = await async_client.get(
            "/internal/worker-deploy-config", headers=INTERNAL_AUTH_HEADER
        )
        assert response.status_code == 200
        data = response.json()
        assert data["allowed_emails"] == ""
        assert data["allowed_email_domain"] == ""
