"""ActivityLog model - stores observability logs for MCP activity."""

from typing import Any
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

# Log types
LogType = Enum(
    "mcp_request",
    "mcp_response",
    "network",
    "alert",
    "error",
    "system",
    "audit",  # Security audit events
    name="log_type",
    create_constraint=True,
)

# Log levels
LogLevel = Enum(
    "debug",
    "info",
    "warning",
    "error",
    name="log_level",
    create_constraint=True,
)


class ActivityLog(BaseModel):
    """Activity log entry for observability.

    Stores MCP requests, responses, network activity, alerts,
    and other observable events from MCP sandboxes.
    """

    __tablename__ = "activity_logs"

    # Optional server association (NULL for system-wide events)
    server_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Log classification
    log_type: Mapped[str] = mapped_column(LogType, nullable=False, index=True)
    level: Mapped[str] = mapped_column(LogLevel, nullable=False, default="info")

    # Log content
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Request correlation (for matching request/response pairs)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Duration tracking (for response logs)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)

    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_activity_logs_server_created", "server_id", "created_at"),
        Index("ix_activity_logs_type_created", "log_type", "created_at"),
        Index("ix_activity_logs_level_created", "level", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ActivityLog {self.log_type} {self.level}: {self.message[:50]}>"

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "server_id": str(self.server_id) if self.server_id else None,
            "log_type": self.log_type,
            "level": self.level,
            "message": self.message,
            "details": self.details,
            "request_id": self.request_id,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
