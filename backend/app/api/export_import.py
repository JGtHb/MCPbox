"""Export/Import API endpoints for backup and migration.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db, settings
from app.models.module_request import ModuleRequest
from app.models.network_access_request import NetworkAccessRequest

if TYPE_CHECKING:
    from app.models.tool import Tool
from app.schemas.server import ServerCreate
from app.schemas.tool import ToolCreate
from app.services.approval import sync_allowed_hosts, sync_allowed_modules
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
class ExportedModuleRequest(BaseModel):
    """Exported module request data."""

    module_name: str
    justification: str
    status: str  # pending, approved, rejected
    requested_by: str | None = None
    reviewed_by: str | None = None
    rejection_reason: str | None = None


class ExportedNetworkAccessRequest(BaseModel):
    """Exported network access request data."""

    host: str
    port: int | None = None
    justification: str
    status: str  # pending, approved, rejected
    requested_by: str | None = None
    reviewed_by: str | None = None
    rejection_reason: str | None = None


class ExportedTool(BaseModel):
    """Exported tool data."""

    name: str
    description: str | None
    enabled: bool
    timeout_ms: int | None
    python_code: str | None
    input_schema: dict | None
    module_requests: list[ExportedModuleRequest] = []
    network_access_requests: list[ExportedNetworkAccessRequest] = []


class ExportedServer(BaseModel):
    """Exported server data."""

    name: str
    description: str | None
    tools: list[ExportedTool]
    allowed_hosts: list[str] = []
    default_timeout_ms: int = 30000
    # v1.2: Admin-originated network access requests (tool_id=NULL, server-scoped)
    admin_network_requests: list[ExportedNetworkAccessRequest] = []


class ExportResponse(BaseModel):
    """Full export response."""

    version: str = "1.2"
    exported_at: str
    servers: list[ExportedServer]
    # v1.2: Admin-originated module requests (tool_id=NULL, global)
    admin_module_requests: list[ExportedModuleRequest] = []
    signature: str | None = None  # HMAC signature for integrity verification


class ImportServerRequest(BaseModel):
    """Request to import a single server."""

    name: str
    description: str | None = None
    tools: list[ExportedTool] = []
    allowed_hosts: list[str] = []
    default_timeout_ms: int = 30000
    # v1.2: Admin-originated network access requests
    admin_network_requests: list[ExportedNetworkAccessRequest] = []


class ImportRequest(BaseModel):
    """Request to import multiple servers."""

    version: str = "1.0"
    servers: list[ImportServerRequest]
    # v1.2: Admin-originated module requests (global)
    admin_module_requests: list[ExportedModuleRequest] = []
    signature: str | None = None  # HMAC signature for integrity verification


class ImportResult(BaseModel):
    """Result of an import operation."""

    success: bool
    servers_created: int
    tools_created: int
    module_requests_created: int = 0
    network_access_requests_created: int = 0
    errors: list[str]
    warnings: list[str] = []


def _export_tool(tool: "Tool") -> ExportedTool:
    """Build an ExportedTool from a Tool ORM object."""
    return ExportedTool(
        name=tool.name,
        description=tool.description,
        enabled=tool.enabled,
        timeout_ms=tool.timeout_ms,
        python_code=tool.python_code,
        input_schema=tool.input_schema,
        module_requests=[
            ExportedModuleRequest(
                module_name=mr.module_name,
                justification=mr.justification,
                status=mr.status,
                requested_by=mr.requested_by,
                reviewed_by=mr.reviewed_by,
                rejection_reason=mr.rejection_reason,
            )
            for mr in tool.module_requests
        ],
        network_access_requests=[
            ExportedNetworkAccessRequest(
                host=nar.host,
                port=nar.port,
                justification=nar.justification,
                status=nar.status,
                requested_by=nar.requested_by,
                reviewed_by=nar.reviewed_by,
                rejection_reason=nar.rejection_reason,
            )
            for nar in tool.network_access_requests
        ],
    )


@router.get("/servers", response_model=ExportResponse)
async def export_all_servers(
    server_service: ServerService = Depends(get_server_service),
    db: AsyncSession = Depends(get_db),
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
            _export_tool(tool) for tool in server.tools if tool.tool_type == "python_code"
        ]

        # Export admin-originated network access requests for this server
        admin_nar_result = await db.execute(
            select(NetworkAccessRequest).where(
                NetworkAccessRequest.server_id == server.id,
                NetworkAccessRequest.tool_id.is_(None),
            )
        )
        admin_network_requests = [
            ExportedNetworkAccessRequest(
                host=nar.host,
                port=nar.port,
                justification=nar.justification,
                status=nar.status,
                requested_by=nar.requested_by,
                reviewed_by=nar.reviewed_by,
                rejection_reason=nar.rejection_reason,
            )
            for nar in admin_nar_result.scalars().all()
        ]

        exported_servers.append(
            ExportedServer(
                name=server.name,
                description=server.description,
                tools=exported_tools,
                allowed_hosts=server.allowed_hosts or [],
                default_timeout_ms=server.default_timeout_ms,
                admin_network_requests=admin_network_requests,
            )
        )

    # Export admin-originated module requests (global, tool_id=NULL)
    admin_mr_result = await db.execute(select(ModuleRequest).where(ModuleRequest.tool_id.is_(None)))
    admin_module_requests = [
        ExportedModuleRequest(
            module_name=mr.module_name,
            justification=mr.justification,
            status=mr.status,
            requested_by=mr.requested_by,
            reviewed_by=mr.reviewed_by,
            rejection_reason=mr.rejection_reason,
        )
        for mr in admin_mr_result.scalars().all()
    ]

    # Build data for signature - exclude exported_at to ensure roundtrip works
    # (import reconstructs data without exported_at for verification)
    signature_data = {
        "version": "1.2",
        "servers": [s.model_dump() for s in exported_servers],
        "admin_module_requests": [m.model_dump() for m in admin_module_requests],
    }

    # Compute signature from the data that will be verified during import
    signature = _compute_export_signature(signature_data)

    # Build full response with exported_at (not included in signature)
    exported_at = datetime.now(UTC).isoformat()

    return ExportResponse(
        version="1.2",
        exported_at=exported_at,
        servers=exported_servers,
        admin_module_requests=admin_module_requests,
        signature=signature,
    )


@router.get("/servers/{server_id}", response_model=ExportedServer)
async def export_server(
    server_id: UUID,
    server_service: ServerService = Depends(get_server_service),
    db: AsyncSession = Depends(get_db),
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
        _export_tool(tool) for tool in server.tools if tool.tool_type == "python_code"
    ]

    # Export admin-originated network access requests
    admin_nar_result = await db.execute(
        select(NetworkAccessRequest).where(
            NetworkAccessRequest.server_id == server.id,
            NetworkAccessRequest.tool_id.is_(None),
        )
    )
    admin_network_requests = [
        ExportedNetworkAccessRequest(
            host=nar.host,
            port=nar.port,
            justification=nar.justification,
            status=nar.status,
            requested_by=nar.requested_by,
            reviewed_by=nar.reviewed_by,
            rejection_reason=nar.rejection_reason,
        )
        for nar in admin_nar_result.scalars().all()
    ]

    return ExportedServer(
        name=server.name,
        description=server.description,
        tools=exported_tools,
        allowed_hosts=server.allowed_hosts or [],
        default_timeout_ms=server.default_timeout_ms,
        admin_network_requests=admin_network_requests,
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

    v1.2: Creates request records first, then syncs caches via helpers.
    v1.0/v1.1: Creates admin records from allowed_hosts for backward compat.
    """
    errors = []
    warnings = []
    is_v1_2 = data.version == "1.2"

    # Reconstruct the same data structure that was signed during export.
    # Must include all ExportedServer fields (name, description, tools,
    # allowed_hosts, default_timeout_ms) to match the export signature.
    # v1.0 exports were signed without module/network request fields,
    # so we strip them for backward-compatible signature verification.
    is_v1_0 = data.version == "1.0"
    servers_list: list[dict] = []
    for s in data.servers:
        tools_list = []
        for t in s.tools:
            tool_dict = t.model_dump()
            if is_v1_0:
                tool_dict.pop("module_requests", None)
                tool_dict.pop("network_access_requests", None)
            tools_list.append(tool_dict)
        server_dict: dict = {
            "name": s.name,
            "description": s.description,
            "tools": tools_list,
            "allowed_hosts": s.allowed_hosts,
            "default_timeout_ms": s.default_timeout_ms,
        }
        if is_v1_2:
            server_dict["admin_network_requests"] = [
                anr.model_dump() for anr in s.admin_network_requests
            ]
        servers_list.append(server_dict)

    import_data: dict = {
        "version": data.version,
        "servers": servers_list,
    }
    if is_v1_2:
        import_data["admin_module_requests"] = [m.model_dump() for m in data.admin_module_requests]

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
    module_requests_created = 0
    network_access_requests_created = 0
    imported_server_ids: list[UUID] = []

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
                server.default_timeout_ms = server_data.default_timeout_ms
                imported_server_ids.append(server.id)

                # Track tool-originated hosts for v1.0/v1.1 backward compat
                tool_originated_hosts: set[str] = set()

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

                    # Create module requests from export data
                    for mr_data in tool_data.module_requests:
                        mr = ModuleRequest(
                            tool_id=tool.id,
                            server_id=server.id,
                            module_name=mr_data.module_name,
                            justification=mr_data.justification,
                            status=mr_data.status,
                            requested_by="import",
                            reviewed_by=mr_data.reviewed_by,
                            rejection_reason=mr_data.rejection_reason,
                        )
                        if mr_data.status != "pending":
                            mr.reviewed_at = datetime.now(UTC)
                        db.add(mr)
                        module_requests_created += 1

                    # Create network access requests from export data
                    for nar_data in tool_data.network_access_requests:
                        nar = NetworkAccessRequest(
                            tool_id=tool.id,
                            server_id=server.id,
                            host=nar_data.host,
                            port=nar_data.port,
                            justification=nar_data.justification,
                            status=nar_data.status,
                            requested_by="import",
                            reviewed_by=nar_data.reviewed_by,
                            rejection_reason=nar_data.rejection_reason,
                        )
                        if nar_data.status != "pending":
                            nar.reviewed_at = datetime.now(UTC)
                        db.add(nar)
                        network_access_requests_created += 1
                        if nar_data.status == "approved":
                            tool_originated_hosts.add(nar_data.host)

                # Import admin-originated network access requests (v1.2)
                if is_v1_2:
                    for anr_data in server_data.admin_network_requests:
                        anr = NetworkAccessRequest(
                            server_id=server.id,
                            tool_id=None,
                            host=anr_data.host,
                            port=anr_data.port,
                            justification=anr_data.justification,
                            status=anr_data.status,
                            requested_by=anr_data.requested_by or "import",
                            reviewed_by=anr_data.reviewed_by,
                            rejection_reason=anr_data.rejection_reason,
                        )
                        if anr_data.status != "pending":
                            anr.reviewed_at = datetime.now(UTC)
                        db.add(anr)
                        network_access_requests_created += 1
                else:
                    # v1.0/v1.1 backward compat: create admin records from
                    # allowed_hosts that don't match tool-originated records
                    for host in server_data.allowed_hosts or []:
                        if host not in tool_originated_hosts:
                            anr = NetworkAccessRequest(
                                server_id=server.id,
                                tool_id=None,
                                host=host,
                                port=None,
                                justification="Pre-existing host (imported from v1.x backup)",
                                status="approved",
                                requested_by="admin",
                                reviewed_by="import",
                                reviewed_at=datetime.now(UTC),
                            )
                            db.add(anr)
                            network_access_requests_created += 1

                # Only count as success if we get here without exception
                servers_created += 1
                tools_created += server_tools_created

            except Exception as e:
                # Savepoint will be rolled back automatically
                errors.append(
                    f"Failed to import server '{server_data.name}': {e!s}. "
                    "Server and all its tools were not imported."
                )

    # Import admin-originated module requests (v1.2, global)
    if is_v1_2:
        for amr_data in data.admin_module_requests:
            mr = ModuleRequest(
                server_id=None,
                tool_id=None,
                module_name=amr_data.module_name,
                justification=amr_data.justification,
                status=amr_data.status,
                requested_by=amr_data.requested_by or "import",
                reviewed_by=amr_data.reviewed_by,
                rejection_reason=amr_data.rejection_reason,
            )
            if amr_data.status != "pending":
                mr.reviewed_at = datetime.now(UTC)
            db.add(mr)
            module_requests_created += 1

    # Sync caches from records (never write arrays directly)
    for sid in imported_server_ids:
        await sync_allowed_hosts(sid, db)
    await sync_allowed_modules(db)

    await db.commit()

    return ImportResult(
        success=len(errors) == 0,
        servers_created=servers_created,
        tools_created=tools_created,
        module_requests_created=module_requests_created,
        network_access_requests_created=network_access_requests_created,
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
