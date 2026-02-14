"""Global configuration model - stores application-wide settings."""

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class GlobalConfig(BaseModel):
    """Global configuration settings.

    Stores application-wide settings like allowed Python modules.
    Only one row should exist (singleton pattern enforced by application logic).
    """

    __tablename__ = "global_config"

    # Unique key to enforce singleton pattern
    config_key: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        default="main",
    )

    # Allowed Python modules for sandbox execution
    # If NULL or empty, uses default safe modules list from sandbox
    # SECURITY: Forbidden modules are always blocked regardless of this setting
    allowed_modules: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(255)),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<GlobalConfig {self.config_key}>"
