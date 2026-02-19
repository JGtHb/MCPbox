"""Tool service - business logic for tool management."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Tool, ToolVersion
from app.schemas.tool import (
    ToolCreate,
    ToolUpdate,
    ToolVersionDiff,
    extract_input_schema_from_python,
)
from app.services.setting import SettingService

logger = logging.getLogger(__name__)


class ToolService:
    """Service for managing MCP tools."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        server_id: UUID,
        data: ToolCreate,
        change_source: str = "manual",
    ) -> Tool:
        """Create a new tool for a server.

        Uses Python code main() signature to extract input schema.
        """
        # Extract input schema from Python code
        input_schema = extract_input_schema_from_python(data.python_code)

        tool = Tool(
            server_id=server_id,
            name=data.name,
            description=data.description,
            python_code=data.python_code,
            input_schema=input_schema,
            enabled=True,
            current_version=1,
        )
        self.db.add(tool)
        await self.db.flush()
        await self.db.refresh(tool)

        # Create initial version
        await self._create_version(
            tool,
            change_summary="Initial version",
            change_source=change_source,
        )

        return tool

    async def get(self, tool_id: UUID) -> Tool | None:
        """Get a tool by ID."""
        result = await self.db.execute(select(Tool).where(Tool.id == tool_id))
        return result.scalar_one_or_none()

    async def get_with_server(self, tool_id: UUID) -> Tool | None:
        """Get a tool by ID with its server relationship eagerly loaded."""
        result = await self.db.execute(
            select(Tool).where(Tool.id == tool_id).options(selectinload(Tool.server))
        )
        return result.scalar_one_or_none()

    async def list_by_server(
        self, server_id: UUID, page: int = 1, page_size: int = 50
    ) -> tuple[list[Tool], int]:
        """List tools for a server with pagination.

        Returns a tuple of (tools, total_count).
        """
        # Get total count
        count_result = await self.db.execute(
            select(func.count(Tool.id)).where(Tool.server_id == server_id)
        )
        total = count_result.scalar() or 0

        # Get paginated results
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(Tool)
            .where(Tool.server_id == server_id)
            .order_by(Tool.created_at.asc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def update(
        self,
        tool_id: UUID,
        data: ToolUpdate,
        change_summary: str | None = None,
        change_source: str = "manual",
    ) -> Tool | None:
        """Update a tool.

        Regenerates input_schema when python_code changes.
        Creates a new version entry to track the change.
        """
        tool = await self.get(tool_id)
        if not tool:
            return None

        update_data = data.model_dump(exclude_unset=True)

        # Check if there are actual changes
        has_changes = False
        for field, value in update_data.items():
            current_value = getattr(tool, field, None)
            if hasattr(value, "model_dump"):
                value = value.model_dump()
            if current_value != value:
                has_changes = True
                break

        if not has_changes:
            return tool  # No changes, skip versioning

        # If python_code is updated, regenerate input_schema
        if "python_code" in update_data and update_data["python_code"]:
            update_data["input_schema"] = extract_input_schema_from_python(
                update_data["python_code"]
            )
            # SECURITY: Reset approval when code changes to prevent TOCTOU bypass
            # (SEC-001) — approved tool having its code silently replaced
            # Exception: auto-approve mode skips review for all code changes
            if tool.python_code != update_data["python_code"]:
                setting_service = SettingService(self.db)
                approval_mode = await setting_service.get_value(
                    "tool_approval_mode", default="require_approval"
                )
                if approval_mode == "auto_approve":
                    update_data["approval_status"] = "approved"
                    update_data["approved_at"] = datetime.now(UTC)
                    update_data["approved_by"] = "auto_approve"
                else:
                    update_data["approval_status"] = "pending_review"

        # Apply updates
        for field, value in update_data.items():
            setattr(tool, field, value)

        # Increment version number atomically to prevent race conditions
        # Using SQL expression ensures database-level atomicity
        stmt = (
            update(Tool).where(Tool.id == tool.id).values(current_version=Tool.current_version + 1)
        )
        await self.db.execute(stmt)

        await self.db.flush()
        await self.db.refresh(tool)

        # Create new version entry
        await self._create_version(
            tool,
            change_summary=change_summary or self._generate_change_summary(update_data),
            change_source=change_source,
        )

        return tool

    async def delete(self, tool_id: UUID) -> bool:
        """Delete a tool."""
        tool = await self.get(tool_id)
        if not tool:
            return False

        await self.db.delete(tool)
        await self.db.flush()
        return True

    async def toggle_enabled(self, tool_id: UUID, enabled: bool) -> Tool | None:
        """Enable or disable a tool."""
        tool = await self.get(tool_id)
        if not tool:
            return None

        tool.enabled = enabled
        await self.db.flush()
        await self.db.refresh(tool)
        return tool

    # Version management methods

    async def _create_version(
        self,
        tool: Tool,
        change_summary: str,
        change_source: str = "manual",
    ) -> ToolVersion:
        """Create a version entry for the current tool state."""
        version = ToolVersion(
            tool_id=tool.id,
            version_number=tool.current_version,
            name=tool.name,
            description=tool.description,
            enabled=tool.enabled,
            timeout_ms=tool.timeout_ms,
            python_code=tool.python_code,
            input_schema=tool.input_schema,
            change_summary=change_summary,
            change_source=change_source,
        )
        self.db.add(version)
        await self.db.flush()
        return version

    def _generate_change_summary(self, update_data: dict[str, Any]) -> str:
        """Generate a human-readable summary of what changed."""
        fields_changed = list(update_data.keys())
        if not fields_changed:
            return "No changes"

        # Map field names to human-readable descriptions
        field_names = {
            "name": "name",
            "description": "description",
            "enabled": "enabled status",
            "timeout_ms": "timeout",
            "python_code": "Python code",
        }

        readable = [field_names.get(f, f) for f in fields_changed]
        if len(readable) == 1:
            return f"Updated {readable[0]}"
        elif len(readable) == 2:
            return f"Updated {readable[0]} and {readable[1]}"
        else:
            return f"Updated {', '.join(readable[:-1])}, and {readable[-1]}"

    async def list_versions(
        self, tool_id: UUID, page: int = 1, page_size: int = 50
    ) -> tuple[list[ToolVersion], int]:
        """List versions of a tool with pagination, newest first.

        Returns a tuple of (versions, total_count).
        """
        # Get total count
        count_result = await self.db.execute(
            select(func.count(ToolVersion.id)).where(ToolVersion.tool_id == tool_id)
        )
        total = count_result.scalar() or 0

        # Get paginated results
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(ToolVersion)
            .where(ToolVersion.tool_id == tool_id)
            .order_by(ToolVersion.version_number.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def get_version(self, tool_id: UUID, version_number: int) -> ToolVersion | None:
        """Get a specific version of a tool."""
        result = await self.db.execute(
            select(ToolVersion).where(
                ToolVersion.tool_id == tool_id,
                ToolVersion.version_number == version_number,
            )
        )
        return result.scalar_one_or_none()

    async def rollback(self, tool_id: UUID, version_number: int) -> Tool | None:
        """Rollback a tool to a previous version.

        Creates a new version entry with change_source='rollback'.
        """
        tool = await self.get(tool_id)
        if not tool:
            return None

        target_version = await self.get_version(tool_id, version_number)
        if not target_version:
            return None

        # Apply the version's state to the tool
        tool.name = target_version.name
        tool.description = target_version.description
        tool.enabled = target_version.enabled
        tool.timeout_ms = target_version.timeout_ms
        tool.python_code = target_version.python_code
        tool.input_schema = target_version.input_schema
        # SECURITY: Reset approval on rollback — rolled-back code needs re-review
        # (SEC-002) — rolling back to different code while keeping "approved" status
        # Exception: auto-approve mode skips review for all code changes
        setting_service = SettingService(self.db)
        approval_mode = await setting_service.get_value(
            "tool_approval_mode", default="require_approval"
        )
        if approval_mode == "auto_approve":
            tool.approval_status = "approved"
            tool.approved_at = datetime.now(UTC)
            tool.approved_by = "auto_approve"
            logger.info(
                f"Tool {tool.name} rollback auto-approved (tool_approval_mode=auto_approve)"
            )
        else:
            tool.approval_status = "pending_review"

        # Increment version number atomically to prevent race conditions
        # Using SQL expression ensures database-level atomicity
        stmt = (
            update(Tool).where(Tool.id == tool.id).values(current_version=Tool.current_version + 1)
        )
        await self.db.execute(stmt)

        await self.db.flush()
        await self.db.refresh(tool)

        # Create version entry for the rollback
        await self._create_version(
            tool,
            change_summary=f"Rolled back to version {version_number}",
            change_source="rollback",
        )

        return tool

    def compare_versions(self, v1: ToolVersion, v2: ToolVersion) -> list[ToolVersionDiff]:
        """Compare two versions and return the differences."""
        fields_to_compare = [
            "name",
            "description",
            "enabled",
            "timeout_ms",
            "python_code",
        ]

        differences = []
        for field in fields_to_compare:
            old_val = getattr(v1, field)
            new_val = getattr(v2, field)

            if old_val != new_val:
                differences.append(
                    ToolVersionDiff(
                        field=field,
                        old_value=old_val,
                        new_value=new_val,
                    )
                )

        return differences
