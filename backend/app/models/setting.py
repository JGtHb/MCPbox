"""Setting model for application configuration."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Setting(BaseModel):
    """Application setting stored as key-value pair.

    Used for storing configuration like:
    - LLM API keys (encrypted)
    - Model preferences
    - Feature toggles
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="Setting key (unique identifier)",
    )

    value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Setting value (may be encrypted for sensitive data)",
    )

    encrypted: Mapped[bool] = mapped_column(
        default=False,
        comment="Whether the value is encrypted",
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Human-readable description of this setting",
    )

    def __repr__(self) -> str:
        return f"<Setting(key={self.key!r})>"
