"""Server model - represents an MCP server configuration."""

from typing import TYPE_CHECKING

from sqlalchemy import Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.external_mcp_source import ExternalMCPSource
    from app.models.server_secret import ServerSecret
    from app.models.tool import Tool

ServerStatus = Enum(
    "imported",
    "ready",
    "running",
    "stopped",
    "error",
    name="server_status",
    create_constraint=True,
)

NetworkMode = Enum(
    "isolated",
    "allowlist",
    name="network_mode",
    create_constraint=True,
)


class Server(BaseModel):
    """MCP Server model.

    Represents an MCP server with tools that run in the shared sandbox.
    """

    __tablename__ = "servers"

    # Basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(
        ServerStatus,
        nullable=False,
        default="imported",
    )

    # Network configuration
    network_mode: Mapped[str] = mapped_column(
        NetworkMode,
        nullable=False,
        default="isolated",
    )
    allowed_hosts: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(255)),
        nullable=True,
    )

    # Resource limits (per architecture doc)
    default_timeout_ms: Mapped[int] = mapped_column(
        Integer,
        default=30000,
        nullable=False,
    )

    # NOTE: allowed_modules has been moved to global_config table
    # Module whitelist is now global, not per-server

    # Relationships
    tools: Mapped[list["Tool"]] = relationship(
        "Tool",
        back_populates="server",
        cascade="all, delete-orphan",
    )
    secrets: Mapped[list["ServerSecret"]] = relationship(
        "ServerSecret",
        back_populates="server",
        cascade="all, delete-orphan",
    )
    external_mcp_sources: Mapped[list["ExternalMCPSource"]] = relationship(
        "ExternalMCPSource",
        back_populates="server",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Server {self.name} ({self.status})>"
