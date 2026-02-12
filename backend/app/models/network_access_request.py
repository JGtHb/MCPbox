"""NetworkAccessRequest model - LLM requests for network whitelist."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
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
    """Network access whitelist request from LLM.

    When an LLM needs to access an external host that is not in the server's
    allowed_hosts list, it can create a NetworkAccessRequest. The admin can
    then review and approve/reject.
    """

    __tablename__ = "network_access_requests"

    # Partial unique index to prevent duplicate pending requests for same host/port
    # This enforces atomicity at the database level, preventing race conditions
    # Note: The actual index uses COALESCE(port, 0) to handle NULL values correctly
    # (created via raw SQL in migration 0023 since SQLAlchemy Index doesn't support COALESCE)
    __table_args__ = (
        Index(
            "ix_network_access_requests_pending_unique",
            "tool_id",
            "host",
            "port",
            unique=True,
            postgresql_where="status = 'pending'",
        ),
    )

    # The tool that needs this network access
    tool_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=False,
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
    tool: Mapped["Tool"] = relationship("Tool", back_populates="network_access_requests")

    def __repr__(self) -> str:
        port_str = f":{self.port}" if self.port else ""
        return (
            f"<NetworkAccessRequest {self.host}{port_str} for tool={self.tool_id} ({self.status})>"
        )
