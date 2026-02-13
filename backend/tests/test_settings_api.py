"""Tests for settings API endpoints."""

import pytest
from httpx import AsyncClient


class TestListSettings:
    """Tests for GET /settings endpoint."""

    @pytest.mark.asyncio
    async def test_list_settings_empty(self, async_client: AsyncClient, admin_headers):
        """Test listing settings when none exist."""
        response = await async_client.get("/api/settings/settings", headers=admin_headers)

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

        response = await async_client.get("/api/settings/settings", headers=admin_headers)

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

        response = await async_client.get("/api/settings/settings", headers=admin_headers)

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

        response = await async_client.get("/api/settings/settings", headers=admin_headers)

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

        response = await async_client.get("/api/settings/settings", headers=admin_headers)

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
