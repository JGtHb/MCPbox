"""Setting service - business logic for app configuration."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting
from app.services.crypto import (
    DecryptionError,
    InvalidKeyError,
    decrypt_from_base64,
    encrypt_to_base64,
)

logger = logging.getLogger(__name__)


class SettingService:
    """Service for managing application settings."""

    # Mask pattern for encrypted values
    MASKED_VALUE = "••••••••"

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, key: str) -> Setting | None:
        """Get a setting by key."""
        result = await self.db.execute(select(Setting).where(Setting.key == key))
        return result.scalar_one_or_none()

    async def get_value(self, key: str, default: str | None = None) -> str | None:
        """Get a setting value by key, decrypting if necessary."""
        setting = await self.get(key)
        if not setting or setting.value is None:
            return default

        if setting.encrypted:
            try:
                return decrypt_from_base64(setting.value, aad=f"setting:{key}")
            except (DecryptionError, InvalidKeyError) as e:
                # Don't silently return a default — that hides key mismatches
                # and data corruption.  Surface the error so operators notice
                # immediately (e.g., MCPBOX_ENCRYPTION_KEY was changed).
                logger.error(
                    "Failed to decrypt setting '%s': %s. "
                    "This usually means MCPBOX_ENCRYPTION_KEY does not match "
                    "the key used to encrypt the stored value.",
                    key,
                    e,
                )
                raise
        return setting.value

    async def get_all(self) -> list[Setting]:
        """Get all settings."""
        result = await self.db.execute(select(Setting).order_by(Setting.key))
        return list(result.scalars().all())

    async def set_value(
        self,
        key: str,
        value: str | None,
        encrypt_value: bool = False,
        description: str | None = None,
    ) -> Setting:
        """Set a setting value, creating if it doesn't exist."""
        setting = await self.get(key)

        if setting is None:
            # Create new setting
            setting = Setting(
                key=key,
                encrypted=encrypt_value,
                description=description,
            )
            self.db.add(setting)

        # Encrypt if needed (using base64 encoding for storage)
        if value is not None and encrypt_value:
            setting.value = encrypt_to_base64(value, aad=f"setting:{key}")
        else:
            setting.value = value

        setting.encrypted = encrypt_value

        await self.db.flush()
        await self.db.refresh(setting)
        return setting

    async def delete(self, key: str) -> bool:
        """Delete a setting."""
        setting = await self.get(key)
        if not setting:
            return False

        await self.db.delete(setting)
        await self.db.flush()
        return True

    def mask_value(self, setting: Setting) -> str:
        """Return masked value for encrypted settings."""
        if setting.encrypted and setting.value:
            return self.MASKED_VALUE
        return setting.value or ""
