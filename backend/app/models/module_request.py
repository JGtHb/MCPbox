"""ModuleRequest model - LLM requests for module whitelisting."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
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
    """Module whitelist request from LLM.

    When an LLM needs a Python module that is not in the server's whitelist,
    it can create a ModuleRequest. The admin can then review and approve/reject.
    """

    __tablename__ = "module_requests"

    # Partial unique index to prevent duplicate pending requests for same module
    # This enforces atomicity at the database level, preventing race conditions
    __table_args__ = (
        Index(
            "ix_module_requests_pending_unique",
            "tool_id",
            "module_name",
            unique=True,
            postgresql_where="status = 'pending'",
        ),
    )

    # The tool that needs this module
    tool_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=False,
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
    tool: Mapped["Tool"] = relationship("Tool", back_populates="module_requests")

    def __repr__(self) -> str:
        return f"<ModuleRequest {self.module_name} for tool={self.tool_id} ({self.status})>"
