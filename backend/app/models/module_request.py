"""ModuleRequest model - requests for module whitelisting.

Supports both LLM-initiated requests (tool_id set) and admin-initiated
additions (tool_id NULL). Modules are global, so server_id is NULL for
admin-initiated requests and denormalized from tool.server_id for LLM requests.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.server import Server
    from app.models.tool import Tool

# Request status enum (shared with NetworkAccessRequest)
RequestStatus = Enum(
    "pending",
    "approved",
    "rejected",
    name="request_status",
    create_constraint=True,
)


class ModuleRequest(BaseModel):
    """Module whitelist request.

    Created by LLMs (via mcpbox_request_module) or by admins (via manual
    module addition). The request table is the single source of truth;
    GlobalConfig.allowed_modules is a derived cache.
    """

    __tablename__ = "module_requests"

    # Two partial unique indexes (created via raw SQL in migration 0002):
    # - ix_mr_pending_tool_unique: (tool_id, module_name) WHERE pending AND tool_id IS NOT NULL
    # - ix_mr_pending_admin_unique: (module_name) WHERE pending AND tool_id IS NULL
    __table_args__: tuple = ()

    # The tool that needs this module (NULL for admin-initiated)
    tool_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Direct server reference (denormalized from tool.server_id for LLM requests,
    # NULL for admin-initiated global module additions)
    server_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Module being requested
    module_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Why the module is needed
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
    tool: Mapped["Tool | None"] = relationship("Tool", back_populates="module_requests")
    server: Mapped["Server | None"] = relationship(
        "Server",
        foreign_keys=[server_id],
        back_populates="module_requests",
    )

    def __repr__(self) -> str:
        source = f"tool={self.tool_id}" if self.tool_id else "admin"
        return f"<ModuleRequest {self.module_name} for {source} ({self.status})>"
