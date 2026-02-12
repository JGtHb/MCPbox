"""Server model - represents an MCP server configuration."""

from typing import TYPE_CHECKING

from sqlalchemy import Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.credential import Credential
    from app.models.tool import Tool

# Server status
# Note: "building" is vestigial from per-server container architecture,
# kept for database enum compatibility
ServerStatus = Enum(
    "imported",
    "building",
    "ready",
    "running",
    "stopped",
    "error",
    name="server_status",
    create_constraint=True,
)

# Network mode
# Note: "monitored" and "learning" are unused, kept for database enum compatibility
NetworkMode = Enum(
    "isolated",
    "allowlist",
    "monitored",
    "learning",
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

    # Python code helpers (shared across all actions in this tool)
    # Contains Python code that can be imported by action code via:
    #   from _helpers import some_function
    # Example use cases: pagination helpers, response parsers, constants
    helper_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    # NOTE: allowed_modules has been moved to global_config table
    # Module whitelist is now global, not per-server

    # Relationships
    tools: Mapped[list["Tool"]] = relationship(
        "Tool",
        back_populates="server",
        cascade="all, delete-orphan",
    )
    credentials: Mapped[list["Credential"]] = relationship(
        "Credential",
        back_populates="server",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Server {self.name} ({self.status})>"
