"""Tool model - represents an MCP tool exposed by a server."""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.external_mcp_source import ExternalMCPSource
    from app.models.module_request import ModuleRequest
    from app.models.network_access_request import NetworkAccessRequest
    from app.models.server import Server
    from app.models.tool_version import ToolVersion

# Approval status for tools
# - draft: Tool is being developed, not visible in MCP tools/list
# - pending_review: LLM has requested publish, waiting for admin approval
# - approved: Admin approved, tool is visible and usable
# - rejected: Admin rejected, tool needs revision
ApprovalStatus = Enum(
    "draft",
    "pending_review",
    "approved",
    "rejected",
    name="approval_status",
    create_constraint=True,
)

# Tool type
# - python_code: Tool with Python code executed in sandbox (default)
# - mcp_passthrough: Tool proxied to an external MCP server
ToolType = Enum(
    "python_code",
    "mcp_passthrough",
    name="tool_type",
    create_constraint=True,
)


class Tool(BaseModel):
    """MCP Tool model.

    Represents a Python code tool that is exposed by an MCP server.
    """

    __tablename__ = "tools"

    # Unique constraint: tool names must be unique within a server
    __table_args__ = (UniqueConstraint("server_id", "name", name="uq_tools_server_id_name"),)

    # Parent server
    server_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Tool metadata (from MCP spec)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # State
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Per-tool timeout (NULL = inherit from server)
    timeout_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Tool type: "python_code" (default) or "mcp_passthrough"
    tool_type: Mapped[str] = mapped_column(
        ToolType,
        nullable=False,
        default="python_code",
        server_default="python_code",
    )

    # Python code for tool execution (python_code tools only)
    # Must contain an async main() function that:
    # - Accepts keyword arguments matching the tool's input schema
    # - Returns the result (dict, list, or primitive)
    # - Has access to injected `http` client (pre-authenticated httpx.AsyncClient)
    # - Can import from _helpers (tool-level shared code)
    python_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    # MCP passthrough fields (mcp_passthrough tools only)
    external_source_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("external_mcp_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Original tool name on the external MCP server
    external_tool_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Dependencies for Python code execution (pip packages)
    code_dependencies: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(255)),
        nullable=True,
    )

    # Current version number (incremented on each update)
    current_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Current version number of this tool",
    )

    # Approval workflow fields
    approval_status: Mapped[str] = mapped_column(
        ApprovalStatus,
        nullable=False,
        default="draft",
    )
    approval_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    publish_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    server: Mapped["Server"] = relationship("Server", back_populates="tools")
    external_source: Mapped["ExternalMCPSource | None"] = relationship(
        "ExternalMCPSource",
        back_populates="tools",
        foreign_keys=[external_source_id],
    )
    versions: Mapped[list["ToolVersion"]] = relationship(
        "ToolVersion",
        back_populates="tool",
        order_by="desc(ToolVersion.version_number)",
        cascade="all, delete-orphan",
    )
    module_requests: Mapped[list["ModuleRequest"]] = relationship(
        "ModuleRequest",
        back_populates="tool",
        cascade="all, delete-orphan",
    )
    network_access_requests: Mapped[list["NetworkAccessRequest"]] = relationship(
        "NetworkAccessRequest",
        back_populates="tool",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Tool {self.name} (server_id={self.server_id}, status={self.approval_status})>"
