"""External MCP Source service - CRUD, discovery, and tool import."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_mcp_source import ExternalMCPSource
from app.models.tool import Tool
from app.schemas.external_mcp_source import (
    DiscoveredTool,
    ExternalMCPSourceCreate,
    ExternalMCPSourceUpdate,
)
from app.services.mcp_oauth_client import get_oauth_auth_headers
from app.services.sandbox_client import SandboxClient

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Result of an import_tools operation with skip details."""

    created: list[Tool] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


class ExternalMCPSourceService:
    """Service for managing external MCP server connections."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, server_id: UUID, data: ExternalMCPSourceCreate) -> ExternalMCPSource:
        """Create a new external MCP source for a server."""
        source = ExternalMCPSource(
            server_id=server_id,
            name=data.name,
            url=data.url,
            auth_type=data.auth_type,
            auth_secret_name=data.auth_secret_name,
            auth_header_name=data.auth_header_name,
            transport_type=data.transport_type,
            status="active",
        )
        self.db.add(source)
        await self.db.flush()
        await self.db.refresh(source)
        return source

    async def get(self, source_id: UUID) -> ExternalMCPSource | None:
        """Get an external MCP source by ID."""
        result = await self.db.execute(
            select(ExternalMCPSource).where(ExternalMCPSource.id == source_id)
        )
        return result.scalar_one_or_none()

    async def list_by_server(self, server_id: UUID) -> list[ExternalMCPSource]:
        """List all external MCP sources for a server."""
        result = await self.db.execute(
            select(ExternalMCPSource)
            .where(ExternalMCPSource.server_id == server_id)
            .order_by(ExternalMCPSource.created_at.desc())
        )
        return list(result.scalars().all())

    async def update(
        self, source_id: UUID, data: ExternalMCPSourceUpdate
    ) -> ExternalMCPSource | None:
        """Update an external MCP source."""
        source = await self.get(source_id)
        if not source:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for attr, value in update_data.items():
            setattr(source, attr, value)

        await self.db.flush()
        await self.db.refresh(source)
        return source

    async def delete(self, source_id: UUID) -> bool:
        """Delete an external MCP source.

        Associated tools will have external_source_id set to NULL (SET NULL FK).
        """
        source = await self.get(source_id)
        if not source:
            return False

        await self.db.delete(source)
        await self.db.flush()
        return True

    async def discover_tools(
        self,
        source_id: UUID,
        sandbox_client: SandboxClient,
        secrets: dict[str, str] | None = None,
    ) -> list[DiscoveredTool]:
        """Discover tools from an external MCP server via the sandbox.

        Args:
            source_id: The external MCP source to discover from.
            sandbox_client: Sandbox client for proxying the discovery request.
            secrets: Decrypted server secrets (for auth credential lookup).

        Returns:
            List of discovered tools.
        """
        source = await self.get(source_id)
        if not source:
            raise ValueError(f"External MCP source {source_id} not found")

        # Build auth headers from source config + server secrets
        auth_headers = await self._build_auth_headers(source, secrets or {})

        # Call sandbox's MCP discover endpoint
        result = await sandbox_client.discover_external_tools(
            url=source.url,
            transport_type=source.transport_type,
            auth_headers=auth_headers,
        )

        if not result.get("success"):
            error = result.get("error", "Unknown error")
            logger.error(f"Discovery failed for source {source.name}: {error}")
            source.status = "error"
            await self.db.flush()
            raise RuntimeError(f"Discovery failed: {error}")

        tools_data = result.get("tools", [])
        discovered = [
            DiscoveredTool(
                name=t["name"],
                description=t.get("description"),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools_data
        ]

        # Update source metadata and cache discovered tools
        source.last_discovered_at = datetime.now(UTC)
        source.tool_count = len(discovered)
        source.status = "active"
        source.discovered_tools_cache = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in discovered
        ]
        await self.db.flush()

        # Mark tools that already exist in this server (check prefixed name)
        existing_result = await self.db.execute(
            select(Tool.name).where(Tool.server_id == source.server_id)
        )
        existing_names = {row[0] for row in existing_result.all()}
        for tool in discovered:
            if self._prefixed_tool_name(source.name, tool.name) in existing_names:
                tool.already_imported = True

        return discovered

    async def get_cached_tools(self, source_id: UUID) -> list[DiscoveredTool] | None:
        """Get cached discovered tools with dynamic already_imported marking.

        Returns None if no cached tools exist (source never discovered).
        Returns list of DiscoveredTool with already_imported computed against
        current server tools.
        """
        source = await self.get(source_id)
        if not source or not source.discovered_tools_cache:
            return None

        # Reconstruct DiscoveredTool objects from cache
        cached = [
            DiscoveredTool(
                name=t["name"],
                description=t.get("description"),
                input_schema=t.get("input_schema", {}),
            )
            for t in source.discovered_tools_cache
        ]

        # Mark tools that already exist in this server (check prefixed name)
        existing_result = await self.db.execute(
            select(Tool.name).where(Tool.server_id == source.server_id)
        )
        existing_names = {row[0] for row in existing_result.all()}
        for tool in cached:
            if self._prefixed_tool_name(source.name, tool.name) in existing_names:
                tool.already_imported = True

        return cached

    async def import_tools(
        self,
        source_id: UUID,
        tool_names: list[str],
        discovered_tools: list[DiscoveredTool],
        auto_approve: bool = False,
    ) -> ImportResult:
        """Import selected tools from an external MCP source.

        Creates Tool records with tool_type="mcp_passthrough".

        Args:
            source_id: The external MCP source.
            tool_names: Names of tools to import.
            discovered_tools: Full list of discovered tools (for metadata).
            auto_approve: If True, set approval_status to "approved" (for admin UI imports).

        Returns:
            ImportResult with created tools and skip details.
        """
        source = await self.get(source_id)
        if not source:
            raise ValueError(f"External MCP source {source_id} not found")

        # Index discovered tools by name
        tool_map = {t.name: t for t in discovered_tools}

        created_tools = []
        skipped_tools = []
        for name in tool_names:
            discovered = tool_map.get(name)
            if not discovered:
                logger.warning(f"Tool '{name}' not found in discovered tools, skipping")
                skipped_tools.append(
                    {
                        "name": name,
                        "status": "skipped_not_found",
                        "reason": f"Tool '{name}' not found in discovered tools",
                    }
                )
                continue

            # Build prefixed name: {source_name}_{tool_name}
            prefixed = self._prefixed_tool_name(source.name, name)

            # Check if tool already exists for this server with same name
            existing = await self.db.execute(
                select(Tool).where(
                    Tool.server_id == source.server_id,
                    Tool.name == prefixed,
                )
            )
            if existing.scalar_one_or_none():
                logger.info(f"Tool '{prefixed}' already exists in server, skipping")
                skipped_tools.append(
                    {
                        "name": name,
                        "status": "skipped_conflict",
                        "reason": f"Tool '{prefixed}' already exists in this server",
                    }
                )
                continue

            tool = Tool(
                server_id=source.server_id,
                name=prefixed,
                description=discovered.description,
                input_schema=discovered.input_schema,
                tool_type="mcp_passthrough",
                external_source_id=source.id,
                external_tool_name=name,
                python_code=None,
                enabled=True,
                approval_status="approved" if auto_approve else "draft",
                current_version=1,
            )
            self.db.add(tool)
            created_tools.append(tool)

        await self.db.flush()
        for tool in created_tools:
            await self.db.refresh(tool)

        return ImportResult(created=created_tools, skipped=skipped_tools)

    async def _build_auth_headers(
        self, source: ExternalMCPSource, secrets: dict[str, str]
    ) -> dict[str, str]:
        """Build HTTP auth headers for an external MCP source."""
        headers: dict[str, str] = {}

        if source.auth_type == "none":
            return headers

        if source.auth_type == "oauth":
            return await self._build_oauth_headers(source)

        if not source.auth_secret_name:
            return headers

        secret_value = secrets.get(source.auth_secret_name)
        if not secret_value:
            logger.warning(
                f"Auth secret '{source.auth_secret_name}' not found for source {source.name}"
            )
            return headers

        if source.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {secret_value}"
        elif source.auth_type == "header":
            header_name = source.auth_header_name or "Authorization"
            headers[header_name] = secret_value

        return headers

    async def _build_oauth_headers(self, source: ExternalMCPSource) -> dict[str, str]:
        """Build auth headers from stored OAuth tokens, refreshing if needed."""
        if not source.oauth_tokens_encrypted:
            logger.warning(
                f"OAuth source '{source.name}' has no tokens. "
                f"Admin needs to authenticate via the UI."
            )
            return {}

        async def update_tokens(new_encrypted: str) -> None:
            source.oauth_tokens_encrypted = new_encrypted
            await self.db.flush()

        return await get_oauth_auth_headers(
            oauth_tokens_encrypted=source.oauth_tokens_encrypted,
            source_id=source.id,
            db_update_callback=update_tokens,
        )

    @staticmethod
    def _sanitize_tool_name(name: str) -> str:
        """Sanitize an external tool name to match MCPbox naming conventions.

        Converts to lowercase, replaces non-alphanumeric chars with underscores,
        ensures it starts with a letter.
        """
        import re

        # Lowercase and replace invalid chars
        sanitized = re.sub(r"[^a-z0-9_]", "_", name.lower())
        # Ensure starts with a letter
        if sanitized and not sanitized[0].isalpha():
            sanitized = "t_" + sanitized
        # Collapse multiple underscores
        sanitized = re.sub(r"_+", "_", sanitized)
        # Strip trailing underscores
        sanitized = sanitized.strip("_")
        return sanitized or "unnamed_tool"

    @classmethod
    def _prefixed_tool_name(cls, source_name: str, tool_name: str) -> str:
        """Build a prefixed tool name: {source_name}_{tool_name}.

        Both parts are sanitized individually, then joined with underscore.
        """
        prefix = cls._sanitize_tool_name(source_name)
        name = cls._sanitize_tool_name(tool_name)
        return f"{prefix}_{name}"
