"""NetworkAccessRequest model - requests for network whitelist.

Supports both LLM-initiated requests (tool_id set) and admin-initiated
additions (tool_id NULL, server_id set directly).
"""

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

# Reuse request_status enum from module_request
RequestStatus = Enum(
    "pending",
    "approved",
    "rejected",
    name="request_status",
    create_constraint=False,  # Already created by module_request migration
)


class NetworkAccessRequest(BaseModel):
    """Network access whitelist request.

    Created by LLMs (via mcpbox_request_network_access) or by admins
    (via manual host addition). The request table is the single source
    of truth; Server.allowed_hosts is a derived cache.
    """

    __tablename__ = "network_access_requests"

    # Two partial unique indexes (created via raw SQL in migration 0002):
    # - ix_nar_pending_tool_unique: (tool_id, host, COALESCE(port,0)) WHERE pending AND tool_id IS NOT NULL
    # - ix_nar_pending_admin_unique: (server_id, host, COALESCE(port,0)) WHERE pending AND tool_id IS NULL
    __table_args__: tuple = ()

    # The tool that needs this network access (NULL for admin-initiated)
    tool_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Direct server reference (denormalized from tool.server_id for LLM requests,
    # set directly for admin requests where tool_id is NULL)
    server_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Host being requested (hostname or IP)
    host: Mapped[str] = mapped_column(String(255), nullable=False)

    # Optional port restriction (NULL = any port)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Why the access is needed
    justification: Mapped[str] = mapped_column(Text, nullable=False)

    # Who requested (email from JWT, if available)
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Review status
    status: Mapped[str] = mapped_column(
        RequestStatus,
        nullable=False,
        default="pending",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    tool: Mapped["Tool | None"] = relationship("Tool", back_populates="network_access_requests")
    server: Mapped["Server | None"] = relationship(
        "Server",
        foreign_keys=[server_id],
        back_populates="network_access_requests",
    )

    def __repr__(self) -> str:
        port_str = f":{self.port}" if self.port else ""
        source = f"tool={self.tool_id}" if self.tool_id else f"server={self.server_id}"
        return f"<NetworkAccessRequest {self.host}{port_str} for {source} ({self.status})>"
