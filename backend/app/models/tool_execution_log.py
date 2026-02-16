"""ToolExecutionLog model - stores execution logs for tool invocations."""

from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class ToolExecutionLog(BaseModel):
    """Execution log entry for a tool invocation.

    Captures input arguments (secrets redacted), result (truncated),
    errors, stdout, duration, and success status.
    """

    __tablename__ = "tool_execution_logs"

    # Tool and server references
    tool_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=False,
    )
    server_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)  # Denormalized for display

    # Execution details
    input_args: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )  # Secrets redacted
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )  # Truncated if large
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Execution metadata
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Actor
    executed_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # User email if available

    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_tool_execution_logs_tool_created", "tool_id", "created_at"),
        Index("ix_tool_execution_logs_server_created", "server_id", "created_at"),
    )

    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"<ToolExecutionLog {status} {self.tool_name} ({self.duration_ms}ms)>"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "tool_id": str(self.tool_id),
            "server_id": str(self.server_id),
            "tool_name": self.tool_name,
            "input_args": self.input_args,
            "result": self.result,
            "error": self.error,
            "stdout": self.stdout,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "executed_by": self.executed_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
