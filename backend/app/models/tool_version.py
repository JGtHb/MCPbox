"""ToolVersion model - stores version history of tools for rollback."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.tool import Tool


class ToolVersion(BaseModel):
    """Version history entry for a tool.

    Stores a snapshot of tool configuration at a point in time,
    enabling version comparison and rollback.
    """

    __tablename__ = "tool_versions"

    # Parent tool
    tool_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Version number (increments with each save)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Snapshot of tool state
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timeout_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    python_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Metadata about this version
    change_summary: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Brief description of what changed in this version",
    )
    change_source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="manual",
        comment="Source of change: manual, llm, import, rollback",
    )

    # Relationship
    tool: Mapped["Tool"] = relationship("Tool", back_populates="versions")

    def __repr__(self) -> str:
        return f"<ToolVersion {self.name} v{self.version_number}>"
