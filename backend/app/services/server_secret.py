"""ServerSecret service - business logic for server secrets management."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server_secret import ServerSecret
from app.services.crypto import decrypt, encrypt

logger = logging.getLogger(__name__)


class ServerSecretService:
    """Service for managing encrypted server secrets."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        server_id: UUID,
        key_name: str,
        description: str | None = None,
    ) -> ServerSecret:
        """Create an empty secret placeholder (no value).

        Value must be set separately by admin via set_value().
        """
        secret = ServerSecret(
            server_id=server_id,
            key_name=key_name,
            description=description,
            encrypted_value=None,
        )
        self.db.add(secret)
        await self.db.flush()
        await self.db.refresh(secret)
        return secret

    async def set_value(
        self,
        server_id: UUID,
        key_name: str,
        value: str,
    ) -> ServerSecret | None:
        """Set or update the encrypted value of a secret.

        Only callable by admin via REST API, never via MCP tools.
        """
        secret = await self._get_by_key(server_id, key_name)
        if not secret:
            return None

        # SECURITY: AAD context binding prevents ciphertext swapping (SEC-005)
        secret.encrypted_value = encrypt(value, aad=f"server_secret:{server_id}:{key_name}")
        await self.db.flush()
        await self.db.refresh(secret)
        return secret

    async def clear_value(
        self,
        server_id: UUID,
        key_name: str,
    ) -> ServerSecret | None:
        """Clear the value of a secret (set back to placeholder)."""
        secret = await self._get_by_key(server_id, key_name)
        if not secret:
            return None

        secret.encrypted_value = None
        await self.db.flush()
        await self.db.refresh(secret)
        return secret

    async def delete(
        self,
        server_id: UUID,
        key_name: str,
    ) -> bool:
        """Delete a secret entirely."""
        secret = await self._get_by_key(server_id, key_name)
        if not secret:
            return False

        await self.db.delete(secret)
        await self.db.flush()
        return True

    async def list_by_server(self, server_id: UUID) -> list[ServerSecret]:
        """List all secrets for a server (values never exposed)."""
        result = await self.db.execute(
            select(ServerSecret)
            .where(ServerSecret.server_id == server_id)
            .order_by(ServerSecret.key_name.asc())
        )
        return list(result.scalars().all())

    async def get_decrypted_for_injection(self, server_id: UUID) -> dict[str, str]:
        """Get all secrets with values as a decrypted dict for sandbox injection.

        Only returns secrets that have values set (ignores placeholders).
        Raises on decryption failure so tool execution fails clearly
        rather than running without expected secrets.
        """
        secrets = await self.list_by_server(server_id)
        result = {}
        for secret in secrets:
            if secret.encrypted_value is not None:
                try:
                    result[secret.key_name] = decrypt(
                        secret.encrypted_value,
                        aad=f"server_secret:{server_id}:{secret.key_name}",
                    )
                except Exception as e:
                    raise RuntimeError(
                        f"Failed to decrypt secret '{secret.key_name}' for "
                        f"server {server_id}. This usually means "
                        f"MCPBOX_ENCRYPTION_KEY does not match the key used "
                        f"to encrypt the stored value."
                    ) from e
        return result

    async def _get_by_key(self, server_id: UUID, key_name: str) -> ServerSecret | None:
        """Get a secret by server_id and key_name."""
        result = await self.db.execute(
            select(ServerSecret).where(
                ServerSecret.server_id == server_id,
                ServerSecret.key_name == key_name,
            )
        )
        return result.scalar_one_or_none()
