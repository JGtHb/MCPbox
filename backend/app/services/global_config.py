"""Global configuration service."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.global_config import GlobalConfig

logger = logging.getLogger(__name__)

# Default allowed modules - these are safe for sandboxed execution
DEFAULT_ALLOWED_MODULES = [
    # Data formats
    "json",
    "base64",
    "binascii",
    "html",
    "csv",
    "xml.etree.ElementTree",
    # String/text processing
    "re",
    "string",
    "textwrap",
    "difflib",
    # Date/time
    "datetime",
    "time",
    "calendar",
    "zoneinfo",
    # Math and numbers
    "math",
    "decimal",
    "fractions",
    "random",
    "statistics",
    # Collections and iteration
    "collections",
    "itertools",
    "functools",
    "operator",
    # Hashing and encoding
    "hashlib",
    "hmac",
    "secrets",
    # URL and web utilities
    "urllib.parse",
    # Data structures
    "dataclasses",
    "typing",
    "enum",
    "copy",
    # Async support
    "asyncio",
    # UUID generation
    "uuid",
    # Context managers
    "contextlib",
]


class GlobalConfigService:
    """Service for managing global configuration."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_config(self) -> GlobalConfig | None:
        """Get the global configuration."""
        result = await self.db.execute(
            select(GlobalConfig).where(GlobalConfig.config_key == "main")
        )
        return result.scalar_one_or_none()

    async def get_or_create_config(self) -> GlobalConfig:
        """Get or create the global configuration."""
        config = await self.get_config()
        if not config:
            config = GlobalConfig(config_key="main")
            self.db.add(config)
            await self.db.flush()
            await self.db.refresh(config)
        return config

    async def get_allowed_modules(self) -> list[str]:
        """Get the allowed modules list.

        Returns the custom list if set, otherwise returns defaults.
        """
        config = await self.get_config()
        if config and config.allowed_modules:
            return config.allowed_modules
        return DEFAULT_ALLOWED_MODULES.copy()

    async def set_allowed_modules(self, modules: list[str]) -> GlobalConfig:
        """Set the allowed modules list."""
        config = await self.get_or_create_config()
        config.allowed_modules = modules
        await self.db.flush()
        await self.db.refresh(config)
        return config

    async def add_module(self, module_name: str) -> tuple[bool, str]:
        """Add a module to the allowed list.

        Returns (success, message).
        """
        modules = await self.get_allowed_modules()
        if module_name in modules:
            return False, f"Module '{module_name}' is already allowed"

        modules.append(module_name)
        await self.set_allowed_modules(modules)
        return True, f"Module '{module_name}' added to allowed list"

    async def remove_module(self, module_name: str) -> tuple[bool, str]:
        """Remove a module from the allowed list.

        Returns (success, message).
        """
        modules = await self.get_allowed_modules()
        if module_name not in modules:
            return False, f"Module '{module_name}' is not in the allowed list"

        modules.remove(module_name)
        await self.set_allowed_modules(modules)
        return True, f"Module '{module_name}' removed from allowed list"

    async def reset_to_defaults(self) -> GlobalConfig:
        """Reset allowed modules to defaults."""
        config = await self.get_or_create_config()
        config.allowed_modules = None  # NULL means use defaults
        await self.db.flush()
        await self.db.refresh(config)
        return config

    async def is_using_defaults(self) -> bool:
        """Check if using default modules."""
        config = await self.get_config()
        return config is None or config.allowed_modules is None

    def get_default_modules(self) -> list[str]:
        """Get the list of default allowed modules."""
        return DEFAULT_ALLOWED_MODULES.copy()
