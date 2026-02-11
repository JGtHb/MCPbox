"""Unit tests for SettingService business logic."""

from unittest.mock import patch

import pytest
import pytest_asyncio

from app.models import Setting
from app.services.setting import SettingService
from app.services.crypto import DecryptionError, InvalidKeyError

pytestmark = pytest.mark.asyncio


class TestSettingServiceGet:
    """Tests for SettingService.get() and get_value()."""

    async def test_get_existing_setting(self, db_session):
        """Get an existing setting by key."""
        setting = Setting(key="test_key", value="test_value", encrypted=False)
        db_session.add(setting)
        await db_session.flush()

        service = SettingService(db_session)
        result = await service.get("test_key")

        assert result is not None
        assert result.key == "test_key"
        assert result.value == "test_value"

    async def test_get_nonexistent_setting(self, db_session):
        """Get non-existent setting returns None."""
        service = SettingService(db_session)

        result = await service.get("nonexistent")

        assert result is None

    async def test_get_value_plain(self, db_session):
        """Get plain (non-encrypted) setting value."""
        setting = Setting(key="plain_key", value="plain_value", encrypted=False)
        db_session.add(setting)
        await db_session.flush()

        service = SettingService(db_session)
        value = await service.get_value("plain_key")

        assert value == "plain_value"

    async def test_get_value_with_default(self, db_session):
        """Get value for non-existent key returns default."""
        service = SettingService(db_session)

        value = await service.get_value("nonexistent", default="default_value")

        assert value == "default_value"

    async def test_get_value_none_returns_default(self, db_session):
        """Get value for setting with None value returns default."""
        setting = Setting(key="null_key", value=None, encrypted=False)
        db_session.add(setting)
        await db_session.flush()

        service = SettingService(db_session)
        value = await service.get_value("null_key", default="fallback")

        assert value == "fallback"

    async def test_get_value_encrypted(self, db_session):
        """Get encrypted setting value decrypts it."""
        from app.services.crypto import encrypt_to_base64

        encrypted = encrypt_to_base64("secret_value")
        setting = Setting(key="encrypted_key", value=encrypted, encrypted=True)
        db_session.add(setting)
        await db_session.flush()

        service = SettingService(db_session)
        value = await service.get_value("encrypted_key")

        assert value == "secret_value"

    async def test_get_value_decryption_error_returns_default(self, db_session):
        """Decryption error returns default value."""
        # Store invalid encrypted value
        setting = Setting(key="bad_encrypted", value="not-valid-base64-crypto", encrypted=True)
        db_session.add(setting)
        await db_session.flush()

        service = SettingService(db_session)
        value = await service.get_value("bad_encrypted", default="fallback")

        assert value == "fallback"

    async def test_get_value_invalid_key_raises(self, db_session):
        """InvalidKeyError is re-raised (needs fixing, not resilience)."""
        from app.services.crypto import encrypt_to_base64

        encrypted = encrypt_to_base64("secret")
        setting = Setting(key="needs_key", value=encrypted, encrypted=True)
        db_session.add(setting)
        await db_session.flush()

        service = SettingService(db_session)

        with patch(
            "app.services.setting.decrypt_from_base64", side_effect=InvalidKeyError("Bad key")
        ):
            with pytest.raises(InvalidKeyError):
                await service.get_value("needs_key")


class TestSettingServiceSet:
    """Tests for SettingService.set_value()."""

    async def test_set_new_setting(self, db_session):
        """Create a new setting."""
        service = SettingService(db_session)

        setting = await service.set_value(
            key="new_key",
            value="new_value",
            description="A new setting",
        )

        assert setting.key == "new_key"
        assert setting.value == "new_value"
        assert setting.description == "A new setting"
        assert setting.encrypted is False

    async def test_set_updates_existing(self, db_session):
        """Update an existing setting."""
        setting = Setting(key="update_key", value="old_value", encrypted=False)
        db_session.add(setting)
        await db_session.flush()

        service = SettingService(db_session)
        updated = await service.set_value("update_key", "new_value")

        assert updated.value == "new_value"
        # Should be same row
        assert updated.id == setting.id

    async def test_set_encrypted_value(self, db_session):
        """Set an encrypted value."""
        service = SettingService(db_session)

        setting = await service.set_value(
            key="secret_key",
            value="secret_value",
            encrypt_value=True,
        )

        assert setting.encrypted is True
        # Stored value should be encrypted (base64)
        assert setting.value != "secret_value"
        # Should be able to decrypt
        value = await service.get_value("secret_key")
        assert value == "secret_value"

    async def test_set_none_value(self, db_session):
        """Set value to None."""
        service = SettingService(db_session)

        setting = await service.set_value("nullable_key", None)

        assert setting.value is None

    async def test_set_changes_encryption_flag(self, db_session):
        """Changing encrypt_value updates the encrypted flag."""
        service = SettingService(db_session)

        # Create unencrypted
        await service.set_value("toggle_key", "value", encrypt_value=False)

        # Update to encrypted
        updated = await service.set_value("toggle_key", "new_secret", encrypt_value=True)

        assert updated.encrypted is True


class TestSettingServiceDelete:
    """Tests for SettingService.delete()."""

    async def test_delete_existing_setting(self, db_session):
        """Delete an existing setting."""
        setting = Setting(key="delete_me", value="value", encrypted=False)
        db_session.add(setting)
        await db_session.flush()

        service = SettingService(db_session)
        result = await service.delete("delete_me")

        assert result is True
        assert await service.get("delete_me") is None

    async def test_delete_nonexistent_setting(self, db_session):
        """Delete non-existent setting returns False."""
        service = SettingService(db_session)

        result = await service.delete("nonexistent")

        assert result is False


class TestSettingServiceGetAll:
    """Tests for SettingService.get_all()."""

    async def test_get_all_settings(self, db_session):
        """Get all settings ordered by key."""
        db_session.add(Setting(key="z_setting", value="z"))
        db_session.add(Setting(key="a_setting", value="a"))
        db_session.add(Setting(key="m_setting", value="m"))
        await db_session.flush()

        service = SettingService(db_session)
        settings = await service.get_all()

        assert len(settings) == 3
        # Should be ordered by key
        assert settings[0].key == "a_setting"
        assert settings[1].key == "m_setting"
        assert settings[2].key == "z_setting"

    async def test_get_all_empty(self, db_session):
        """Get all when no settings exist returns empty list."""
        service = SettingService(db_session)

        settings = await service.get_all()

        assert settings == []


class TestSettingServiceMask:
    """Tests for SettingService.mask_value()."""

    def test_mask_encrypted_value(self, db_session):
        """Encrypted values are masked."""
        setting = Setting(key="secret", value="encrypted_blob", encrypted=True)
        service = SettingService(db_session)

        masked = service.mask_value(setting)

        assert masked == "••••••••"

    def test_mask_plain_value(self, db_session):
        """Plain values are not masked."""
        setting = Setting(key="plain", value="visible_value", encrypted=False)
        service = SettingService(db_session)

        masked = service.mask_value(setting)

        assert masked == "visible_value"

    def test_mask_none_value(self, db_session):
        """None values return empty string."""
        setting = Setting(key="null", value=None, encrypted=False)
        service = SettingService(db_session)

        masked = service.mask_value(setting)

        assert masked == ""

    def test_mask_encrypted_none(self, db_session):
        """Encrypted but None value is not masked."""
        setting = Setting(key="encrypted_null", value=None, encrypted=True)
        service = SettingService(db_session)

        masked = service.mask_value(setting)

        # No value to mask
        assert masked == ""
