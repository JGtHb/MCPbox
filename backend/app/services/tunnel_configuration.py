"""Tunnel Configuration service - business logic for managing tunnel profiles."""

import logging
import math
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TunnelConfiguration
from app.schemas.tunnel_configuration import (
    TunnelConfigurationCreate,
    TunnelConfigurationListPaginatedResponse,
    TunnelConfigurationListResponse,
    TunnelConfigurationResponse,
    TunnelConfigurationUpdate,
)
from app.services.crypto import (
    DecryptionError,
    decrypt_from_base64,
    encrypt_to_base64,
)

logger = logging.getLogger(__name__)


class TunnelConfigurationService:
    """Service for managing tunnel configuration profiles."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> TunnelConfigurationListPaginatedResponse:
        """List all tunnel configurations with pagination."""
        # Get total count
        count_query = select(func.count()).select_from(TunnelConfiguration)
        total = (await self.db.execute(count_query)).scalar() or 0

        # Calculate pagination
        pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size

        # Get items
        query = (
            select(TunnelConfiguration)
            .order_by(TunnelConfiguration.is_active.desc(), TunnelConfiguration.name)
            .offset(offset)
            .limit(page_size)
        )
        result = await self.db.execute(query)
        configs = result.scalars().all()

        items = [
            TunnelConfigurationListResponse(
                id=config.id,
                name=config.name,
                description=config.description,
                public_url=config.public_url,
                is_active=config.is_active,
                has_token=config.tunnel_token is not None,
                created_at=config.created_at,
            )
            for config in configs
        ]

        return TunnelConfigurationListPaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    async def get(self, config_id: UUID) -> TunnelConfiguration | None:
        """Get a tunnel configuration by ID."""
        result = await self.db.execute(
            select(TunnelConfiguration).where(TunnelConfiguration.id == config_id)
        )
        return result.scalar_one_or_none()

    async def get_response(self, config_id: UUID) -> TunnelConfigurationResponse | None:
        """Get a tunnel configuration response by ID."""
        config = await self.get(config_id)
        if not config:
            return None

        return TunnelConfigurationResponse(
            id=config.id,
            name=config.name,
            description=config.description,
            public_url=config.public_url,
            is_active=config.is_active,
            has_token=config.tunnel_token is not None,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

    async def get_active(self) -> TunnelConfiguration | None:
        """Get the currently active tunnel configuration."""
        result = await self.db.execute(
            select(TunnelConfiguration).where(TunnelConfiguration.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        data: TunnelConfigurationCreate,
    ) -> TunnelConfiguration:
        """Create a new tunnel configuration."""
        # Encrypt the tunnel token
        encrypted_token = encrypt_to_base64(data.tunnel_token)

        config = TunnelConfiguration(
            name=data.name,
            description=data.description,
            public_url=data.public_url,
            tunnel_token=encrypted_token,
            is_active=False,  # New configurations are not active by default
        )

        self.db.add(config)
        await self.db.flush()
        await self.db.refresh(config)

        logger.info(f"Created tunnel configuration: {config.name} ({config.id})")
        return config

    async def update(
        self,
        config_id: UUID,
        data: TunnelConfigurationUpdate,
    ) -> TunnelConfiguration | None:
        """Update a tunnel configuration."""
        config = await self.get(config_id)
        if not config:
            return None

        if data.name is not None:
            config.name = data.name
        if data.description is not None:
            config.description = data.description
        if data.public_url is not None:
            config.public_url = data.public_url
        if data.tunnel_token is not None:
            config.tunnel_token = encrypt_to_base64(data.tunnel_token)

        await self.db.flush()
        await self.db.refresh(config)

        logger.info(f"Updated tunnel configuration: {config.name} ({config.id})")
        return config

    async def delete(self, config_id: UUID) -> bool:
        """Delete a tunnel configuration."""
        config = await self.get(config_id)
        if not config:
            return False

        # Prevent deleting active configuration
        if config.is_active:
            raise ValueError("Cannot delete the active tunnel configuration")

        await self.db.delete(config)
        await self.db.flush()

        logger.info(f"Deleted tunnel configuration: {config.name} ({config_id})")
        return True

    async def activate(self, config_id: UUID) -> TunnelConfiguration | None:
        """Activate a tunnel configuration (deactivates all others)."""
        config = await self.get(config_id)
        if not config:
            return None

        # Deactivate all configurations
        await self.db.execute(update(TunnelConfiguration).values(is_active=False))

        # Activate the selected one
        config.is_active = True

        await self.db.flush()
        await self.db.refresh(config)

        logger.info(f"Activated tunnel configuration: {config.name} ({config.id})")
        return config

    async def deactivate_all(self) -> None:
        """Deactivate all tunnel configurations."""
        await self.db.execute(update(TunnelConfiguration).values(is_active=False))
        await self.db.flush()
        logger.info("Deactivated all tunnel configurations")

    async def get_decrypted_token(self, config_id: UUID) -> str | None:
        """Get the decrypted tunnel token for a configuration."""
        config = await self.get(config_id)
        if not config or not config.tunnel_token:
            return None

        try:
            return decrypt_from_base64(config.tunnel_token)
        except DecryptionError as e:
            logger.warning(f"Failed to decrypt tunnel token for {config_id}: {e}")
            return None
