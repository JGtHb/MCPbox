"""API routes for External MCP Sources - connect external MCP servers to MCPbox."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.schemas.external_mcp_source import (
    DiscoverToolsResponse,
    ExternalMCPSourceCreate,
    ExternalMCPSourceResponse,
    ExternalMCPSourceUpdate,
    ImportToolsRequest,
    OAuthExchangeRequest,
    OAuthStartRequest,
    OAuthStartResponse,
)
from app.schemas.tool import ToolResponse
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


def get_server_service(db: AsyncSession = Depends(get_db)) -> ServerService:
    return ServerService(db)


def get_source_service(db: AsyncSession = Depends(get_db)) -> ExternalMCPSourceService:
    return ExternalMCPSourceService(db)


def _source_to_response(source) -> dict:
    """Convert a source model to a response dict with computed fields."""
    return {
        **{c.name: getattr(source, c.name) for c in source.__table__.columns},
        "oauth_authenticated": source.oauth_tokens_encrypted is not None,
    }


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
):
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
):
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
):
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
):
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
):
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
):
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


@router.post(
    "/sources/{source_id}/import",
    response_model=list[ToolResponse],
    status_code=status.HTTP_201_CREATED,
)
async def import_tools(
    source_id: UUID,
    data: ImportToolsRequest,
    db: AsyncSession = Depends(get_db),
    source_service: ExternalMCPSourceService = Depends(get_source_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
):
    """Import selected tools from an external MCP source.

    First discovers tools to get full metadata, then creates Tool records
    for the selected tool names. Tools are created in 'draft' status and
    must be approved before becoming available.
    """
    source = await source_service.get(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External MCP source {source_id} not found",
        )

    # Discover tools to get full metadata
    secret_service = ServerSecretService(db)
    secrets = await secret_service.get_decrypted_for_injection(source.server_id)

    try:
        discovered = await source_service.discover_tools(
            source_id=source_id,
            sandbox_client=sandbox_client,
            secrets=secrets,
        )
    except RuntimeError as e:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    # Import selected tools
    tools = await source_service.import_tools(
        source_id=source_id,
        tool_names=data.tool_names,
        discovered_tools=discovered,
    )

    await db.commit()
    for tool in tools:
        await db.refresh(tool)

    return tools


# --- OAuth ---


@router.post(
    "/sources/{source_id}/oauth/start",
    response_model=OAuthStartResponse,
)
async def oauth_start(
    source_id: UUID,
    data: OAuthStartRequest,
    source_service: ExternalMCPSourceService = Depends(get_source_service),
):
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
):
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
