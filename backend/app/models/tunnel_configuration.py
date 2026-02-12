"""TunnelConfiguration model - represents a named tunnel configuration profile."""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class TunnelConfiguration(BaseModel):
    """Named Tunnel Configuration model.

    Represents a saved tunnel configuration profile that can be activated
    to use with Cloudflare named tunnels. Users can have multiple profiles
    (e.g., "Production", "Development") and switch between them.
    """

    __tablename__ = "tunnel_configurations"

    # Profile info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cloudflare tunnel token (encrypted at service layer)
    # This is the token from Cloudflare Zero Trust Dashboard
    tunnel_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Public URL/hostname for this tunnel
    # e.g., "mcpbox.example.com" or "https://mcpbox.example.com"
    public_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Whether this is the currently active configuration
    # Only one configuration can be active at a time
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        active = " (active)" if self.is_active else ""
        return f"<TunnelConfiguration {self.name}{active}>"
