"""Export/Import API endpoints for backup and migration.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db, settings
from app.schemas.server import ServerCreate
from app.schemas.tool import ToolCreate
from app.services.server import ServerService
from app.services.tool import ToolService


def _compute_export_signature(data: dict) -> str:
    """Compute HMAC-SHA256 signature for export data.

    Uses the encryption key as the signing key to ensure exports
    can only be imported into instances with the same key.

    Raises:
        ValueError: If MCPBOX_ENCRYPTION_KEY is not configured.
    """
    if not settings.mcpbox_encryption_key:
        raise ValueError(
            "MCPBOX_ENCRYPTION_KEY environment variable is required for export signatures. "
            "Generate one with: openssl rand -hex 32"
        )

    # Create a stable JSON representation (sorted keys, no whitespace)
    # Exclude the signature field itself from the hash
    data_copy = {k: v for k, v in data.items() if k != "signature"}
    canonical = json.dumps(data_copy, sort_keys=True, separators=(",", ":"))

    # Use encryption key as HMAC key
    key = settings.mcpbox_encryption_key.encode()
    signature = hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()
    return signature


def _verify_export_signature(data: dict) -> bool:
    """Verify the signature of imported data.

    Returns True if signature is valid, False otherwise.
    """
    provided_signature = data.get("signature")
    if not provided_signature:
        return False

    expected_signature = _compute_export_signature(data)
    return hmac.compare_digest(provided_signature, expected_signature)


router = APIRouter(
    prefix="/export",
    tags=["export-import"],
)


def get_server_service(db: AsyncSession = Depends(get_db)) -> ServerService:
    """Dependency to get server service."""
    return ServerService(db)


def get_tool_service(db: AsyncSession = Depends(get_db)) -> ToolService:
    """Dependency to get tool service."""
    return ToolService(db)


# Export schemas
class ExportedTool(BaseModel):
    """Exported tool data."""

    name: str
    description: str | None
    enabled: bool
    timeout_ms: int | None
    python_code: str | None
    input_schema: dict | None


class ExportedServer(BaseModel):
    """Exported server data."""

    name: str
    description: str | None
    tools: list[ExportedTool]
    allowed_hosts: list[str] = []
    default_timeout_ms: int = 30000


class ExportResponse(BaseModel):
    """Full export response."""

    version: str = "1.0"
    exported_at: str
    servers: list[ExportedServer]
    signature: str | None = None  # HMAC signature for integrity verification


class ImportServerRequest(BaseModel):
    """Request to import a single server."""

    name: str
    description: str | None = None
    tools: list[ExportedTool] = []
    allowed_hosts: list[str] = []
    default_timeout_ms: int = 30000


class ImportRequest(BaseModel):
    """Request to import multiple servers."""

    version: str = "1.0"
    servers: list[ImportServerRequest]
    signature: str | None = None  # HMAC signature for integrity verification


class ImportResult(BaseModel):
    """Result of an import operation."""

    success: bool
    servers_created: int
    tools_created: int
    errors: list[str]
    warnings: list[str] = []


@router.get("/servers", response_model=ExportResponse)
async def export_all_servers(
    server_service: ServerService = Depends(get_server_service),
) -> ExportResponse:
    """Export all servers and their tools.

    Returns a JSON export that can be used for backup or migration.
    NOTE: Credentials are NOT included in the export for security.
    """
    # Use list_with_tools to avoid N+1 queries (fetches all servers + tools in 2 queries)
    servers_list = await server_service.list_with_tools()
    exported_servers = []

    for server in servers_list:
        exported_tools = [
            ExportedTool(
                name=tool.name,
                description=tool.description,
                enabled=tool.enabled,
                timeout_ms=tool.timeout_ms,
                python_code=tool.python_code,
                input_schema=tool.input_schema,
            )
            for tool in server.tools
            if tool.tool_type == "python_code"
        ]

        exported_servers.append(
            ExportedServer(
                name=server.name,
                description=server.description,
                tools=exported_tools,
                allowed_hosts=server.allowed_hosts or [],
                default_timeout_ms=server.default_timeout_ms,
            )
        )

    # Build data for signature - exclude exported_at to ensure roundtrip works
    # (import reconstructs data without exported_at for verification)
    signature_data = {
        "version": "1.0",
        "servers": [s.model_dump() for s in exported_servers],
    }

    # Compute signature from the data that will be verified during import
    signature = _compute_export_signature(signature_data)

    # Build full response with exported_at (not included in signature)
    exported_at = datetime.now(UTC).isoformat()

    return ExportResponse(
        version="1.0",
        exported_at=exported_at,
        servers=exported_servers,
        signature=signature,
    )


@router.get("/servers/{server_id}", response_model=ExportedServer)
async def export_server(
    server_id: UUID,
    server_service: ServerService = Depends(get_server_service),
) -> ExportedServer:
    """Export a single server and its tools."""
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    # server.tools is already eager-loaded by server_service.get()
    exported_tools = [
        ExportedTool(
            name=tool.name,
            description=tool.description,
            enabled=tool.enabled,
            timeout_ms=tool.timeout_ms,
            python_code=tool.python_code,
            input_schema=tool.input_schema,
        )
        for tool in server.tools
        if tool.tool_type == "python_code"
    ]

    return ExportedServer(
        name=server.name,
        description=server.description,
        tools=exported_tools,
        allowed_hosts=server.allowed_hosts or [],
        default_timeout_ms=server.default_timeout_ms,
    )


@router.post("/import", response_model=ImportResult)
async def import_servers(
    data: ImportRequest,
    server_service: ServerService = Depends(get_server_service),
    tool_service: ToolService = Depends(get_tool_service),
    db: AsyncSession = Depends(get_db),
) -> ImportResult:
    """Import servers and tools from an export.

    Creates new servers with new IDs. Does NOT overwrite existing servers.
    Credentials must be configured separately after import.

    SECURITY: Validates signature to ensure data integrity and that the export
    came from a trusted MCPbox instance with the same encryption key.

    Each server import uses a savepoint for atomic server+tools creation.
    If any tool fails, the entire server import is rolled back.
    """
    errors = []
    warnings = []

    # Verify signature for data integrity (warn if invalid, don't block)
    import_data = {
        "version": data.version,
        "servers": [
            {
                "name": s.name,
                "description": s.description,
                "tools": [t.model_dump() for t in s.tools],
            }
            for s in data.servers
        ],
    }

    # SECURITY (F-07): Reject imports with invalid or missing signatures.
    # This prevents social engineering attacks where a crafted export with
    # plausible tool names contains subtle malicious logic.
    if data.signature:
        import_data["signature"] = data.signature
        if not _verify_export_signature(import_data):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Export signature is invalid. The file may have been modified "
                    "or was exported from a different MCPbox instance. "
                    "Import rejected for security."
                ),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Export file is not signed. Unsigned imports are rejected for security. "
                "Use a signed export from a trusted MCPbox instance."
            ),
        )
    servers_created = 0
    tools_created = 0

    for server_data in data.servers:
        # Use a savepoint for each server so we can rollback on failure
        # This ensures we don't end up with partial imports (server without tools)
        async with db.begin_nested():
            try:
                # Check if server with same name already exists
                existing = await server_service.get_by_name(server_data.name)
                if existing:
                    # Append suffix to make name unique
                    import_name = f"{server_data.name} (imported)"
                else:
                    import_name = server_data.name

                # Create server
                server_create = ServerCreate(
                    name=import_name,
                    description=server_data.description,
                )
                server = await server_service.create(server_create)

                # Apply additional settings from export
                server.allowed_hosts = server_data.allowed_hosts or []
                server.default_timeout_ms = server_data.default_timeout_ms

                # Create all tools - if any fail, entire server is rolled back
                server_tools_created = 0
                for tool_data in server_data.tools:
                    if not tool_data.python_code:
                        # Skip tools without code (e.g. mcp_passthrough tools from older exports)
                        warnings.append(
                            f"Skipped tool '{tool_data.name}' in server "
                            f"'{server_data.name}': no python_code (external MCP tool)"
                        )
                        continue
                    tool_create = ToolCreate(
                        name=tool_data.name,
                        description=tool_data.description,
                        timeout_ms=tool_data.timeout_ms,
                        python_code=tool_data.python_code,
                        code_dependencies=None,
                    )
                    tool = await tool_service.create(server.id, tool_create, change_source="import")
                    # Mark imported tools as pending_review so they appear
                    # in the approval queue (create() defaults to draft)
                    tool.approval_status = "pending_review"
                    tool.approval_requested_at = datetime.now(UTC)
                    server_tools_created += 1

                # Only count as success if we get here without exception
                servers_created += 1
                tools_created += server_tools_created

            except Exception as e:
                # Savepoint will be rolled back automatically
                errors.append(
                    f"Failed to import server '{server_data.name}': {e!s}. "
                    "Server and all its tools were not imported."
                )

    await db.commit()

    return ImportResult(
        success=len(errors) == 0,
        servers_created=servers_created,
        tools_created=tools_created,
        errors=errors,
        warnings=warnings,
    )


@router.get("/download/servers")
async def download_export(
    server_service: ServerService = Depends(get_server_service),
) -> JSONResponse:
    """Download all servers as a JSON file."""
    export = await export_all_servers(server_service)

    return JSONResponse(
        content=export.model_dump(mode="json"),
        headers={
            "Content-Disposition": f"attachment; filename=mcpbox-export-{datetime.now(UTC).strftime('%Y%m%d')}.json"
        },
    )
