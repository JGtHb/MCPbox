"""Tests for settings API endpoints."""

import pytest
from httpx import AsyncClient

from app.middleware.rate_limit import RateLimiter


class TestListSettings:
    """Tests for GET /settings endpoint."""

    @pytest.mark.asyncio
    async def test_list_settings_empty(self, async_client: AsyncClient, admin_headers):
        """Test listing settings when none exist."""
        response = await async_client.get("/api/settings", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "settings" in data
        assert isinstance(data["settings"], list)

    @pytest.mark.asyncio
    async def test_list_settings_with_data(
        self, async_client: AsyncClient, db_session, admin_headers
    ):
        """Test listing settings with existing data."""

        from app.models.setting import Setting

        # Create test settings
        setting1 = Setting(
            key="test_key_1",
            value="test_value_1",
            encrypted=False,
            description="Test setting 1",
        )
        setting2 = Setting(
            key="test_key_2",
            value="encrypted_value",
            encrypted=True,
            description="Test setting 2",
        )

        db_session.add(setting1)
        db_session.add(setting2)
        await db_session.flush()

        response = await async_client.get("/api/settings", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data["settings"]) >= 2

        # Find our test settings
        keys = [s["key"] for s in data["settings"]]
        assert "test_key_1" in keys
        assert "test_key_2" in keys

    @pytest.mark.asyncio
    async def test_encrypted_values_masked(
        self, async_client: AsyncClient, db_session, admin_headers
    ):
        """Test that encrypted values are masked in response."""
        from app.models.setting import Setting

        # Create encrypted setting
        setting = Setting(
            key="secret_key",
            value="super_secret_value",
            encrypted=True,
            description="Secret setting",
        )
        db_session.add(setting)
        await db_session.flush()

        response = await async_client.get("/api/settings", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Find the encrypted setting
        secret_setting = next((s for s in data["settings"] if s["key"] == "secret_key"), None)
        assert secret_setting is not None
        assert secret_setting["encrypted"] is True
        # Value should be masked, not the actual value
        assert secret_setting["value"] != "super_secret_value"
        # Accept various masked formats: bullets, asterisks, or [encrypted]
        assert (
            "•" in secret_setting["value"]
            or "***" in secret_setting["value"]
            or secret_setting["value"] == "[encrypted]"
        )

    @pytest.mark.asyncio
    async def test_unencrypted_values_visible(
        self, async_client: AsyncClient, db_session, admin_headers
    ):
        """Test that unencrypted values are visible."""
        from app.models.setting import Setting

        setting = Setting(
            key="public_key",
            value="public_value",
            encrypted=False,
            description="Public setting",
        )
        db_session.add(setting)
        await db_session.flush()

        response = await async_client.get("/api/settings", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        public_setting = next((s for s in data["settings"] if s["key"] == "public_key"), None)
        assert public_setting is not None
        assert public_setting["value"] == "public_value"
        assert public_setting["encrypted"] is False

    @pytest.mark.asyncio
    async def test_settings_response_structure(
        self, async_client: AsyncClient, db_session, admin_headers
    ):
        """Test the structure of settings response."""

        from app.models.setting import Setting

        setting = Setting(
            key="struct_test",
            value="test_value",
            encrypted=False,
            description="Structure test",
        )
        db_session.add(setting)
        await db_session.flush()
        await db_session.refresh(setting)

        response = await async_client.get("/api/settings", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        struct_setting = next((s for s in data["settings"] if s["key"] == "struct_test"), None)
        assert struct_setting is not None

        # Check all required fields are present
        assert "id" in struct_setting
        assert "key" in struct_setting
        assert "value" in struct_setting
        assert "encrypted" in struct_setting
        assert "description" in struct_setting
        assert "updated_at" in struct_setting


class TestSecurityPolicy:
    """Tests for security policy endpoints."""

    @pytest.mark.asyncio
    async def test_get_security_policy_defaults(self, async_client: AsyncClient, admin_headers):
        """Test getting security policy returns defaults."""
        response = await async_client.get("/api/settings/security-policy", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["mcp_rate_limit_rpm"] == 300
        assert data["log_retention_days"] == 30

    @pytest.mark.asyncio
    async def test_update_mcp_rate_limit(self, async_client: AsyncClient, admin_headers):
        """Test updating MCP rate limit via security policy."""
        response = await async_client.patch(
            "/api/settings/security-policy",
            json={"mcp_rate_limit_rpm": 500},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mcp_rate_limit_rpm"] == 500

    @pytest.mark.asyncio
    async def test_mcp_rate_limit_bounds_low(self, async_client: AsyncClient, admin_headers):
        """Test that MCP rate limit rejects values below 10."""
        response = await async_client.patch(
            "/api/settings/security-policy",
            json={"mcp_rate_limit_rpm": 5},
            headers=admin_headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_mcp_rate_limit_bounds_high(self, async_client: AsyncClient, admin_headers):
        """Test that MCP rate limit rejects values above 10000."""
        response = await async_client.patch(
            "/api/settings/security-policy",
            json={"mcp_rate_limit_rpm": 20000},
            headers=admin_headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_mcp_rate_limit_updates_singleton(self, async_client: AsyncClient, admin_headers):
        """Test that updating MCP rate limit updates the in-memory RateLimiter."""
        response = await async_client.patch(
            "/api/settings/security-policy",
            json={"mcp_rate_limit_rpm": 750},
            headers=admin_headers,
        )
        assert response.status_code == 200

        config = RateLimiter.get_instance().get_config_for_path("/mcp")
        assert config.requests_per_minute == 750


class TestSecurityProfile:
    """Tests for PATCH /api/settings/security-profile endpoint."""

    @pytest.mark.asyncio
    async def test_apply_strict_profile(self, async_client: AsyncClient, admin_headers):
        """Test applying the strict security profile."""
        response = await async_client.patch(
            "/api/settings/security-profile",
            json={"profile": "strict"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["profile"] == "strict"
        assert data["applied_settings"]["tool_approval_mode"] == "require_approval"
        assert data["applied_settings"]["network_access_policy"] == "require_approval"
        assert data["applied_settings"]["module_approval_mode"] == "require_approval"
        assert data["applied_settings"]["remote_tool_editing"] == "disabled"

        # Verify settings were actually saved
        response = await async_client.get("/api/settings/security-policy", headers=admin_headers)
        assert response.status_code == 200
        policy = response.json()
        assert policy["tool_approval_mode"] == "require_approval"
        assert policy["remote_tool_editing"] == "disabled"

    @pytest.mark.asyncio
    async def test_apply_balanced_profile(self, async_client: AsyncClient, admin_headers):
        """Test applying the balanced security profile."""
        response = await async_client.patch(
            "/api/settings/security-profile",
            json={"profile": "balanced"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["profile"] == "balanced"
        assert data["applied_settings"]["tool_approval_mode"] == "auto_approve"
        assert data["applied_settings"]["module_approval_mode"] == "auto_approve"
        assert data["applied_settings"]["network_access_policy"] == "require_approval"
        assert data["applied_settings"]["remote_tool_editing"] == "disabled"

    @pytest.mark.asyncio
    async def test_apply_permissive_profile(self, async_client: AsyncClient, admin_headers):
        """Test applying the permissive security profile."""
        response = await async_client.patch(
            "/api/settings/security-profile",
            json={"profile": "permissive"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["profile"] == "permissive"
        assert data["applied_settings"]["tool_approval_mode"] == "auto_approve"
        assert data["applied_settings"]["network_access_policy"] == "allow_all_public"
        assert data["applied_settings"]["remote_tool_editing"] == "enabled"
        # Secret redaction stays enabled even in permissive
        assert data["applied_settings"]["redact_secrets_in_output"] == "enabled"

    @pytest.mark.asyncio
    async def test_invalid_profile_rejected(self, async_client: AsyncClient, admin_headers):
        """Test that an invalid profile name is rejected."""
        response = await async_client.patch(
            "/api/settings/security-profile",
            json={"profile": "nonexistent"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_security_profile_requires_auth(self, async_client: AsyncClient):
        """Test that security profile endpoint requires authentication."""
        response = await async_client.patch(
            "/api/settings/security-profile",
            json={"profile": "strict"},
        )
        assert response.status_code == 401


class TestOnboardingComplete:
    """Tests for POST /api/settings/onboarding-complete endpoint."""

    @pytest.mark.asyncio
    async def test_complete_onboarding(self, async_client: AsyncClient, admin_headers):
        """Test marking onboarding as complete."""
        response = await async_client.post(
            "/api/settings/onboarding-complete", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["onboarding_completed"] is True

    @pytest.mark.asyncio
    async def test_complete_onboarding_idempotent(self, async_client: AsyncClient, admin_headers):
        """Test that completing onboarding is idempotent."""
        # Complete once
        response = await async_client.post(
            "/api/settings/onboarding-complete", headers=admin_headers
        )
        assert response.status_code == 200

        # Complete again — should still succeed
        response = await async_client.post(
            "/api/settings/onboarding-complete", headers=admin_headers
        )
        assert response.status_code == 200
        assert response.json()["onboarding_completed"] is True

    @pytest.mark.asyncio
    async def test_onboarding_complete_requires_auth(self, async_client: AsyncClient):
        """Test that onboarding-complete endpoint requires authentication."""
        response = await async_client.post("/api/settings/onboarding-complete")
        assert response.status_code == 401
