"""ExternalMCPSource model - tracks external MCP servers connected to MCPbox servers."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.server import Server
    from app.models.tool import Tool

# Auth type for connecting to external MCP servers
ExternalMCPAuthType = Enum(
    "none",
    "bearer",
    "header",
    "oauth",
    name="external_mcp_auth_type",
    create_constraint=True,
)

# Transport type for external MCP connections
ExternalMCPTransportType = Enum(
    "streamable_http",
    "sse",
    name="external_mcp_transport_type",
    create_constraint=True,
)

# Status of the external MCP source connection
ExternalMCPSourceStatus = Enum(
    "active",
    "error",
    "disabled",
    name="external_mcp_source_status",
    create_constraint=True,
)


class ExternalMCPSource(BaseModel):
    """Represents a connection to an external MCP server.

    Multiple external MCP sources can be attached to a single MCPbox server.
    Tools from the external server can be selectively imported and exposed
    through the MCPbox server.
    """

    __tablename__ = "external_mcp_sources"

    # Parent MCPbox server
    server_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Human-readable name (e.g., "GitHub MCP", "Slack MCP")
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # External MCP server URL
    url: Mapped[str] = mapped_column(Text, nullable=False)

    # Authentication
    auth_type: Mapped[str] = mapped_column(
        ExternalMCPAuthType,
        nullable=False,
        default="none",
    )
    # Reference to a server secret key name for auth credential
    auth_secret_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Custom header name for auth (default: "Authorization")
    auth_header_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Transport
    transport_type: Mapped[str] = mapped_column(
        ExternalMCPTransportType,
        nullable=False,
        default="streamable_http",
    )

    # Status
    status: Mapped[str] = mapped_column(
        ExternalMCPSourceStatus,
        nullable=False,
        default="active",
    )

    # OAuth 2.1 credentials (MCP spec auth flow)
    # Encrypted JSON blob: {access_token, refresh_token, token_endpoint, expires_at, scope}
    oauth_tokens_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Authorization server URL (for display and re-auth)
    oauth_issuer: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # OAuth client ID (from DCR or manual config)
    oauth_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Discovery metadata
    last_discovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    tool_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    server: Mapped["Server"] = relationship("Server", back_populates="external_mcp_sources")
    tools: Mapped[list["Tool"]] = relationship(
        "Tool",
        back_populates="external_source",
        foreign_keys="Tool.external_source_id",
    )

    def __repr__(self) -> str:
        return f"<ExternalMCPSource {self.name} ({self.url}) server_id={self.server_id}>"
