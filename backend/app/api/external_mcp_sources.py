"""API routes for External MCP Sources - connect external MCP servers to MCPbox."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.schemas.external_mcp_source import (
    DiscoverToolsResponse,
    ExternalMCPSourceCreate,
    ExternalMCPSourceResponse,
    ExternalMCPSourceUpdate,
    HealthCheckResponse,
    ImportToolResult,
    ImportToolsRequest,
    ImportToolsResponse,
    OAuthExchangeRequest,
    OAuthStartRequest,
    OAuthStartResponse,
)
from app.models.server import Server
from app.services.external_mcp_source import ExternalMCPSourceService
from app.services.mcp_oauth_client import (
    OAuthDiscoveryError,
    OAuthError,
    OAuthTokenError,
    encrypt_tokens,
    exchange_code,
    start_oauth_flow,
)
from app.services.sandbox_client import SandboxClient, get_sandbox_client
from app.services.server import ServerService
from app.services.server_secret import ServerSecretService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/external-sources", tags=["external-mcp-sources"])


async def _refresh_server_after_import(server: Server, db: AsyncSession) -> bool:
    """Re-register a running server with the sandbox after importing new tools.

    Loads all approved+enabled tools from DB and re-registers the full set
    with the sandbox, so newly imported tools are immediately available.
    Includes mcp_passthrough tool definitions and external source configs.

    Returns True if successful, False otherwise.
    """
    try:
        from app.api.sandbox import _build_external_source_configs, _build_tool_definitions
        from app.services.global_config import GlobalConfigService
        from app.services.server_secret import ServerSecretService as SecretSvc
        from app.services.tool import ToolService

        # Get all tools for this server (the builder filters as needed)
        tool_service = ToolService(db)
        tools, _ = await tool_service.list_by_server(server.id)

        # Filter to approved + enabled only
        active_tools = [t for t in tools if t.enabled and t.approval_status == "approved"]

        # Build tool definitions (handles both python_code and mcp_passthrough)
        tool_defs = _build_tool_definitions(active_tools)

        # Get decrypted secrets
        secret_service = SecretSvc(db)
        secrets = await secret_service.get_decrypted_for_injection(server.id)

        # Get global allowed modules
        config_service = GlobalConfigService(db)
        allowed_modules = await config_service.get_allowed_modules()

        # Build external source configs for passthrough tools
        external_sources_data = await _build_external_source_configs(db, server.id, secrets)

        # Re-register with sandbox
        sandbox_client = SandboxClient.get_instance()
        reg_result = await sandbox_client.register_server(
            server_id=str(server.id),
            server_name=server.name,
            tools=tool_defs,
            allowed_modules=allowed_modules,
            secrets=secrets,
            external_sources=external_sources_data,
        )

        success = (
            bool(reg_result.get("success")) if isinstance(reg_result, dict) else bool(reg_result)
        )
        if success:
            logger.info(
                f"Server {server.name} re-registered with {len(tool_defs)} tools after import"
            )
        else:
            logger.warning(f"Failed to re-register server {server.name} after import")
        return success

    except Exception as e:
        logger.error(f"Error refreshing server registration after import: {e}")
        return False


def get_server_service(db: AsyncSession = Depends(get_db)) -> ServerService:
    return ServerService(db)


def get_source_service(db: AsyncSession = Depends(get_db)) -> ExternalMCPSourceService:
    return ExternalMCPSourceService(db)


def _source_to_response(source: Any) -> dict[str, Any]:
    """Convert a source model to a response dict with computed fields."""
    from app.schemas.external_mcp_source import ExternalMCPSourceResponse

    data = ExternalMCPSourceResponse.model_validate(source).model_dump()
    data["oauth_authenticated"] = source.oauth_tokens_encrypted is not None
    return data


# --- Source CRUD ---


@router.post(
    "/servers/{server_id}/sources",
    response_model=ExternalMCPSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_source(
    server_id: UUID,
    data: ExternalMCPSourceCreate,
    db: AsyncSession = Depends(get_db),
    server_service: ServerService = Depends(get_server_service),
    source_service: ExternalMCPSourceService = Depends(get_source_service),
) -> dict[str, Any]:
    """Create a new external MCP source for a server."""
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    source = await source_service.create(server_id, data)
    await db.commit()
    await db.refresh(source)
    return _source_to_response(source)


@router.get(
    "/servers/{server_id}/sources",
    response_model=list[ExternalMCPSourceResponse],
)
async def list_sources(
    server_id: UUID,
    server_service: ServerService = Depends(get_server_service),
    source_service: ExternalMCPSourceService = Depends(get_source_service),
) -> list[dict[str, Any]]:
    """List all external MCP sources for a server."""
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    sources = await source_service.list_by_server(server_id)
    return [_source_to_response(s) for s in sources]


@router.get(
    "/sources/{source_id}",
    response_model=ExternalMCPSourceResponse,
)
async def get_source(
    source_id: UUID,
    source_service: ExternalMCPSourceService = Depends(get_source_service),
) -> dict[str, Any]:
    """Get an external MCP source by ID."""
    source = await source_service.get(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External MCP source {source_id} not found",
        )
    return _source_to_response(source)


@router.put(
    "/sources/{source_id}",
    response_model=ExternalMCPSourceResponse,
)
async def update_source(
    source_id: UUID,
    data: ExternalMCPSourceUpdate,
    db: AsyncSession = Depends(get_db),
    source_service: ExternalMCPSourceService = Depends(get_source_service),
) -> dict[str, Any]:
    """Update an external MCP source."""
    source = await source_service.update(source_id, data)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External MCP source {source_id} not found",
        )
    await db.commit()
    return _source_to_response(source)


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    source_service: ExternalMCPSourceService = Depends(get_source_service),
) -> None:
    """Delete an external MCP source."""
    deleted = await source_service.delete(source_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External MCP source {source_id} not found",
        )
    await db.commit()


# --- Discovery & Import ---


@router.post(
    "/sources/{source_id}/discover",
    response_model=DiscoverToolsResponse,
)
async def discover_tools(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    source_service: ExternalMCPSourceService = Depends(get_source_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> DiscoverToolsResponse:
    """Discover available tools from an external MCP server.

    Connects to the external server via the sandbox, performs the MCP
    handshake, and returns the list of available tools.
    """
    source = await source_service.get(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External MCP source {source_id} not found",
        )

    # Get decrypted secrets for auth credential lookup
    secret_service = ServerSecretService(db)
    secrets = await secret_service.get_decrypted_for_injection(source.server_id)

    try:
        discovered = await source_service.discover_tools(
            source_id=source_id,
            sandbox_client=sandbox_client,
            secrets=secrets,
        )
        await db.commit()

        return DiscoverToolsResponse(
            source_id=source.id,
            source_name=source.name,
            tools=discovered,
            total=len(discovered),
        )
    except RuntimeError as e:
        await db.commit()  # Persist error status
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e


@router.get(
    "/sources/{source_id}/cached-tools",
    response_model=DiscoverToolsResponse,
)
async def get_cached_tools(
    source_id: UUID,
    source_service: ExternalMCPSourceService = Depends(get_source_service),
) -> DiscoverToolsResponse:
    """Get cached discovered tools for a source.

    Returns cached tools with already_imported computed dynamically against
    current server tools. Returns empty list if never discovered.
    """
    source = await source_service.get(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External MCP source {source_id} not found",
        )

    cached = await source_service.get_cached_tools(source_id)
    tools = cached or []

    return DiscoverToolsResponse(
        source_id=source.id,
        source_name=source.name,
        tools=tools,
        total=len(tools),
    )


@router.post(
    "/sources/{source_id}/import",
    response_model=ImportToolsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_tools(
    source_id: UUID,
    data: ImportToolsRequest,
    db: AsyncSession = Depends(get_db),
    source_service: ExternalMCPSourceService = Depends(get_source_service),
    server_service: ServerService = Depends(get_server_service),
) -> ImportToolsResponse:
    """Import selected tools from an external MCP source.

    Uses cached discovered tools instead of re-discovering. Admin imports
    are auto-approved and trigger MCP client notifications if the server
    is running.
    """
    source = await source_service.get(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External MCP source {source_id} not found",
        )

    # Use cached tools instead of re-discovering
    cached = await source_service.get_cached_tools(source_id)
    if cached is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No cached tools available. Discover tools first.",
        )

    # Import selected tools from cache (auto-approve since admin is importing directly)
    result = await source_service.import_tools(
        source_id=source_id,
        tool_names=data.tool_names,
        discovered_tools=cached,
        auto_approve=True,
    )

    await db.commit()
    for tool in result.created:
        await db.refresh(tool)

    # Re-register server with sandbox and notify MCP clients so new tools
    # are immediately available without requiring a server restart
    if result.created:
        try:
            server = await server_service.get(source.server_id)
            if server and server.status == "running":
                await _refresh_server_after_import(server, db)

                from app.services.tool_change_notifier import fire_and_forget_notify

                fire_and_forget_notify()
        except Exception as e:
            logger.warning(f"Failed to refresh server after import: {e}")

    return ImportToolsResponse(
        created=[
            ImportToolResult(
                name=t.name,
                status="created",
                tool_id=t.id,
            )
            for t in result.created
        ],
        skipped=[
            ImportToolResult(
                name=s["name"],
                status=s["status"],
                reason=s["reason"],
            )
            for s in result.skipped
        ],
        total_requested=len(data.tool_names),
        total_created=len(result.created),
        total_skipped=len(result.skipped),
    )


# --- Health Check ---


@router.post(
    "/sources/{source_id}/health",
    response_model=HealthCheckResponse,
)
async def health_check_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    source_service: ExternalMCPSourceService = Depends(get_source_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> HealthCheckResponse:
    """Check connectivity to an external MCP server.

    Performs an MCP initialize handshake to verify the server is reachable
    and responding to MCP protocol requests. Updates the source status
    based on the result.
    """
    source = await source_service.get(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External MCP source {source_id} not found",
        )

    # Get decrypted secrets for auth credential lookup
    secret_service = ServerSecretService(db)
    secrets = await secret_service.get_decrypted_for_injection(source.server_id)
    auth_headers = await source_service._build_auth_headers(source, secrets)

    result = await sandbox_client.health_check_external(
        url=source.url,
        auth_headers=auth_headers,
    )

    # Update source status based on health check result
    if result.get("healthy"):
        source.status = "active"
    else:
        source.status = "error"
    await db.commit()

    return HealthCheckResponse(
        source_id=source.id,
        source_name=source.name,
        healthy=result.get("healthy", False),
        latency_ms=result.get("latency_ms", 0),
        error=result.get("error"),
    )


# --- OAuth ---


@router.post(
    "/sources/{source_id}/oauth/start",
    response_model=OAuthStartResponse,
)
async def oauth_start(
    source_id: UUID,
    data: OAuthStartRequest,
    source_service: ExternalMCPSourceService = Depends(get_source_service),
) -> OAuthStartResponse:
    """Start the OAuth 2.1 authorization flow for an external MCP source.

    Discovers OAuth metadata from the external server, registers a client
    if needed, and returns the authorization URL for the browser popup.
    """
    source = await source_service.get(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External MCP source {source_id} not found",
        )

    if source.auth_type != "oauth":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source auth_type must be 'oauth' to use OAuth flow.",
        )

    try:
        result = await start_oauth_flow(
            source_id=source.id,
            mcp_url=source.url,
            callback_url=data.callback_url,
            existing_client_id=source.oauth_client_id,
        )
        return OAuthStartResponse(
            auth_url=result["auth_url"],
            issuer=result["issuer"],
        )
    except OAuthDiscoveryError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OAuth discovery failed: {e}",
        ) from e
    except OAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post(
    "/oauth/exchange",
)
async def oauth_exchange(
    data: OAuthExchangeRequest,
    db: AsyncSession = Depends(get_db),
    source_service: ExternalMCPSourceService = Depends(get_source_service),
) -> dict[str, Any]:
    """Exchange an OAuth authorization code for tokens.

    Called by the frontend after the admin completes authentication in
    the browser popup. Stores encrypted tokens on the source.
    """
    try:
        source_id, tokens = await exchange_code(data.state, data.code)
    except OAuthTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    source = await source_service.get(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated external source not found.",
        )

    # Store encrypted tokens
    source.oauth_tokens_encrypted = encrypt_tokens(tokens, source.oauth_client_id)
    if not source.oauth_issuer:
        source.oauth_issuer = tokens.token_endpoint.rsplit("/", 1)[0]

    await db.flush()
    await db.commit()

    return {"success": True, "source_id": str(source_id)}
