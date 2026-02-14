"""Credential service - business logic for credential management."""

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Credential
from app.schemas.credential import (
    CredentialCreate,
    CredentialForInjection,
    CredentialUpdate,
)
from app.services.crypto import decrypt, encrypt

logger = logging.getLogger(__name__)


class CredentialEncryptionError(Exception):
    """Raised when credential encryption/decryption fails.

    This includes failures during both create and update operations,
    with context about which field caused the failure.
    """


class CredentialService:
    """Service for managing encrypted credentials."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, server_id: UUID, data: CredentialCreate) -> Credential:
        """Create a new credential with encrypted values.

        Raises:
            CredentialEncryptionError: If encryption fails for any field
        """
        credential = Credential(
            server_id=server_id,
            name=data.name,
            description=data.description,
            auth_type=data.auth_type,
            header_name=data.header_name,
            query_param_name=data.query_param_name,
            oauth_client_id=data.oauth_client_id,
            oauth_token_url=data.oauth_token_url,
            oauth_scopes=data.oauth_scopes,
            oauth_grant_type=data.oauth_grant_type,
            oauth_authorization_url=data.oauth_authorization_url,
        )

        # Encrypt sensitive values with error handling
        # Track current field for better error messages
        current_field = None
        try:
            if data.value:
                current_field = "value"
                credential.encrypted_value = encrypt(data.value)
            if data.username:
                current_field = "username"
                credential.encrypted_username = encrypt(data.username)
            if data.password:
                current_field = "password"
                credential.encrypted_password = encrypt(data.password)
            if data.oauth_client_secret:
                current_field = "oauth_client_secret"
                credential.oauth_client_secret = encrypt(data.oauth_client_secret)
            if data.access_token:
                current_field = "access_token"
                credential.encrypted_access_token = encrypt(data.access_token)
            if data.refresh_token:
                current_field = "refresh_token"
                credential.encrypted_refresh_token = encrypt(data.refresh_token)
        except Exception as e:
            field_info = f" (field: {current_field})" if current_field else ""
            logger.error(f"Failed to encrypt credential '{data.name}'{field_info}: {e}")
            raise CredentialEncryptionError(
                f"Failed to encrypt credential '{data.name}'{field_info}: {e}"
            ) from e

        self.db.add(credential)
        await self.db.flush()
        await self.db.refresh(credential)
        return credential

    async def get(self, credential_id: UUID) -> Credential | None:
        """Get a credential by ID."""
        result = await self.db.execute(select(Credential).where(Credential.id == credential_id))
        return result.scalar_one_or_none()

    async def list_by_server(
        self, server_id: UUID, page: int = 1, page_size: int = 50
    ) -> tuple[list[Credential], int]:
        """List credentials for a server with pagination.

        Returns a tuple of (credentials, total_count).
        """
        # Get total count
        count_result = await self.db.execute(
            select(func.count(Credential.id)).where(Credential.server_id == server_id)
        )
        total = count_result.scalar() or 0

        # Get paginated results
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(Credential)
            .where(Credential.server_id == server_id)
            .order_by(Credential.created_at.asc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def list_all_by_server(self, server_id: UUID) -> list[Credential]:
        """List all credentials for a server without pagination.

        Used internally for injection where all credentials are needed.
        """
        result = await self.db.execute(
            select(Credential)
            .where(Credential.server_id == server_id)
            .order_by(Credential.created_at.asc())
        )
        return list(result.scalars().all())

    async def update(self, credential_id: UUID, data: CredentialUpdate) -> Credential | None:
        """Update a credential.

        Raises:
            CredentialEncryptionError: If encryption fails for any field
        """
        credential = await self.get(credential_id)
        if not credential:
            return None

        # Update non-encrypted fields
        if data.name is not None:
            credential.name = data.name
        if data.description is not None:
            credential.description = data.description

        # Update encrypted fields with error handling
        # Track current field for better error messages
        current_field = None
        try:
            if data.value is not None:
                current_field = "value"
                credential.encrypted_value = encrypt(data.value)
            if data.username is not None:
                current_field = "username"
                credential.encrypted_username = encrypt(data.username)
            if data.password is not None:
                current_field = "password"
                credential.encrypted_password = encrypt(data.password)
            if data.access_token is not None:
                current_field = "access_token"
                credential.encrypted_access_token = encrypt(data.access_token)
            if data.refresh_token is not None:
                current_field = "refresh_token"
                credential.encrypted_refresh_token = encrypt(data.refresh_token)
        except Exception as e:
            field_info = f" (field: {current_field})" if current_field else ""
            logger.error(
                f"Failed to encrypt credential update for '{credential_id}'{field_info}: {e}"
            )
            raise CredentialEncryptionError(
                f"Failed to encrypt credential update for '{credential_id}'{field_info}: {e}"
            ) from e

        await self.db.flush()
        await self.db.refresh(credential)
        return credential

    async def delete(self, credential_id: UUID) -> bool:
        """Delete a credential."""
        credential = await self.get(credential_id)
        if not credential:
            return False

        await self.db.delete(credential)
        await self.db.flush()
        return True

    async def get_for_injection(self, server_id: UUID) -> list[CredentialForInjection]:
        """Get all credentials for a server with decrypted values.

        This is used internally when injecting credentials into containers.
        """
        credentials = await self.list_all_by_server(server_id)
        result = []

        for cred in credentials:
            injection = CredentialForInjection(
                name=cred.name,
                auth_type=cred.auth_type,
                header_name=cred.header_name,
                query_param_name=cred.query_param_name,
                value=self._decrypt_if_present(cred.encrypted_value),
                username=self._decrypt_if_present(cred.encrypted_username),
                password=self._decrypt_if_present(cred.encrypted_password),
                access_token=self._decrypt_if_present(cred.encrypted_access_token),
            )
            result.append(injection)

        return result

    def _decrypt_if_present(self, encrypted: bytes | None) -> str | None:
        """Decrypt a value if it exists.

        Returns None if decryption fails (logs warning) to avoid breaking
        injection for other credentials.
        """
        if encrypted:
            try:
                return decrypt(encrypted)
            except Exception as e:
                logger.warning(f"Failed to decrypt credential value: {e}")
                return None
        return None
