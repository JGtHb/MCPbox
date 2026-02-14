"""Cloudflare remote access wizard API endpoints.

Provides a step-by-step wizard to configure Cloudflare remote access:
1. Login with Cloudflare OAuth
2. Create Cloudflare tunnel
3. Create VPC service for private tunnel access
4. Deploy MCPbox proxy Worker
5. Create MCP Server
6. Create MCP Portal
7. Configure Worker JWT verification
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.cloudflare import (
    ConfigureJwtRequest,
    ConfigureJwtResponse,
    CreateMcpPortalRequest,
    CreateMcpPortalResponse,
    CreateMcpServerRequest,
    CreateMcpServerResponse,
    CreateTunnelRequest,
    CreateTunnelResponse,
    CreateVpcServiceRequest,
    CreateVpcServiceResponse,
    DeployWorkerRequest,
    DeployWorkerResponse,
    SetApiTokenRequest,
    SetApiTokenResponse,
    StartWithApiTokenRequest,
    StartWithApiTokenResponse,
    TeardownResponse,
    WizardStatusResponse,
    Zone,
)
from app.services.cloudflare import CloudflareAPIError, CloudflareService, ResourceConflictError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cloudflare", tags=["cloudflare"])


def get_cloudflare_service(db: AsyncSession = Depends(get_db)) -> CloudflareService:
    """Dependency to get CloudflareService instance."""
    return CloudflareService(db)


# =============================================================================
# Status
# =============================================================================


@router.get("/status", response_model=WizardStatusResponse)
async def get_wizard_status(
    service: CloudflareService = Depends(get_cloudflare_service),
) -> WizardStatusResponse:
    """Get current wizard status and configuration.

    Returns the current state of the Cloudflare remote access setup,
    including which steps have been completed and any error messages.
    """
    return await service.get_status()


# =============================================================================
# Step 1: API Token Authentication (Primary Method)
# =============================================================================


@router.post("/start", response_model=StartWithApiTokenResponse)
async def start_with_api_token(
    request: StartWithApiTokenRequest,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> StartWithApiTokenResponse:
    """Start the wizard with an API token.

    This is the primary authentication method. Verifies the token,
    retrieves account information, and creates a configuration.

    Required token permissions:
    - Account > Cloudflare Tunnel > Edit
    - Account > Access: Apps and Policies > Edit
    - Account > Workers Scripts > Edit
    - Zone > Zone > Read (for all zones)
    """
    try:
        result = await service.start_with_api_token(request.api_token)
        if result.success:
            await db.commit()
        return result
    except Exception:
        logger.exception("Failed to start with API token")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start with API token. Check server logs for details.",
        ) from None


@router.post("/api-token", response_model=SetApiTokenResponse)
async def set_api_token(
    request: SetApiTokenRequest,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> SetApiTokenResponse:
    """Set an API token for operations requiring higher permissions.

    The wrangler OAuth token doesn't include permissions for tunnel creation
    or MCP server/portal management. This endpoint allows setting a proper
    API token with those permissions.

    Required token permissions:
    - Account > Cloudflare Tunnel > Edit
    - Account > Access: Apps and Policies > Edit
    - Account > MCP Portals > Edit
    """
    try:
        result = await service.set_api_token(request.config_id, request.api_token)
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None


# =============================================================================
# Step 2: Create Tunnel
# =============================================================================


@router.post("/tunnel", response_model=CreateTunnelResponse)
async def create_tunnel(
    request: CreateTunnelRequest,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> CreateTunnelResponse:
    """Create a Cloudflare tunnel.

    Creates a new Cloudflare tunnel that will be used to route traffic
    from the internet to your local MCPbox instance.

    Returns the tunnel token which is stored in the database and
    automatically used by the cloudflared container on startup.
    """
    try:
        result = await service.create_tunnel(request.config_id, request.name, force=request.force)
        await db.commit()
        return result
    except ResourceConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(e),
                "existing_resources": e.existing_resources,
            },
        ) from None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    except CloudflareAPIError as e:
        await db.commit()  # Commit error state
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from None


# =============================================================================
# Step 3: Create VPC Service
# =============================================================================


@router.post("/vpc-service", response_model=CreateVpcServiceResponse)
async def create_vpc_service(
    request: CreateVpcServiceRequest,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> CreateVpcServiceResponse:
    """Create a VPC service for private tunnel access.

    Creates a virtual network that allows the Cloudflare Worker to
    access the tunnel privately, without exposing a public hostname.
    """
    try:
        result = await service.create_vpc_service(
            request.config_id, request.name, force=request.force
        )
        await db.commit()
        return result
    except ResourceConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(e),
                "existing_resources": e.existing_resources,
            },
        ) from None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    except CloudflareAPIError as e:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from None


# =============================================================================
# Step 4: Deploy Worker
# =============================================================================


@router.post("/worker", response_model=DeployWorkerResponse)
async def deploy_worker(
    request: DeployWorkerRequest,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> DeployWorkerResponse:
    """Deploy the MCPbox proxy Worker.

    Note: Full Worker deployment with VPC bindings requires the wrangler CLI.
    This endpoint provides guidance for manual deployment.
    """
    try:
        result = await service.deploy_worker(request.config_id, request.name)
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    except CloudflareAPIError as e:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from None


# =============================================================================
# Step 5: Create MCP Server
# =============================================================================


@router.post("/mcp-server", response_model=CreateMcpServerResponse)
async def create_mcp_server(
    request: CreateMcpServerRequest,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> CreateMcpServerResponse:
    """Create an MCP Server in Cloudflare.

    Creates an MCP Server that points to your Worker URL.
    The server is configured with auth_type: "unauthenticated" because
    authentication is handled by the MCP Portal.
    """
    try:
        result = await service.create_mcp_server(
            request.config_id,
            request.server_id,
            request.server_name,
            request.access_policy,
            force=request.force,
        )
        await db.commit()
        return result
    except ResourceConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(e),
                "existing_resources": e.existing_resources,
            },
        ) from None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    except CloudflareAPIError as e:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from None


# =============================================================================
# Sync MCP Server Tools
# =============================================================================


@router.post("/sync-tools/{config_id}")
async def sync_mcp_server_tools(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> dict:
    """Manually sync MCP server tools with Cloudflare.

    This can be called after JWT is configured to allow Cloudflare
    to enumerate the tools from the Worker endpoint.

    Returns the number of tools discovered.
    """
    try:
        result = await service.sync_mcp_server(config_id)
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    except CloudflareAPIError as e:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from None


# =============================================================================
# Step 6: Create MCP Portal
# =============================================================================


@router.post("/mcp-portal", response_model=CreateMcpPortalResponse)
async def create_mcp_portal(
    request: CreateMcpPortalRequest,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> CreateMcpPortalResponse:
    """Create an MCP Portal in Cloudflare.

    Creates an MCP Portal that provides OAuth authentication for users
    accessing your MCP tools through Claude Web.
    """
    try:
        result = await service.create_mcp_portal(
            request.config_id,
            request.portal_id,
            request.portal_name,
            request.hostname,
            request.access_policy,
            force=request.force,
        )
        await db.commit()
        return result
    except ResourceConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(e),
                "existing_resources": e.existing_resources,
            },
        ) from None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    except CloudflareAPIError as e:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from None


# =============================================================================
# Step 7: Configure Worker JWT
# =============================================================================


@router.post("/worker-jwt-config", response_model=ConfigureJwtResponse)
async def configure_worker_jwt(
    request: ConfigureJwtRequest,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> ConfigureJwtResponse:
    """Configure Worker JWT verification.

    Provides the values needed to set Worker secrets for JWT verification.
    After setting secrets, direct Worker access (bypassing the MCP Portal)
    will return 401 Unauthorized.

    If the AUD cannot be fetched automatically, it can be provided manually
    in the request.
    """
    try:
        result = await service.configure_worker_jwt(request.config_id, request.aud)
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    except Exception:
        logger.exception("Failed to configure Worker JWT")
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to configure Worker JWT. Check server logs for details.",
        ) from None


# =============================================================================
# Teardown
# =============================================================================


@router.delete("/teardown/{config_id}", response_model=TeardownResponse)
async def teardown(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> TeardownResponse:
    """Remove all Cloudflare resources created by the wizard.

    Deletes the MCP Portal, MCP Server, VPC Service, and Tunnel.
    The Worker must be deleted manually using wrangler.
    """
    try:
        result = await service.teardown(config_id)
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    except CloudflareAPIError as e:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from None


# =============================================================================
# Get Tunnel Token
# =============================================================================


@router.get("/tunnel-token/{config_id}")
async def get_tunnel_token(
    config_id: UUID,
    service: CloudflareService = Depends(get_cloudflare_service),
) -> dict:
    """Get the tunnel token for a configuration.

    Returns the decrypted tunnel token. The token is stored in the
    database and automatically used by the cloudflared container.
    """
    token = await service.get_tunnel_token(config_id)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tunnel token not found",
        )
    return {"tunnel_token": token}


# =============================================================================
# Get Zones
# =============================================================================


@router.get("/zones/{config_id}")
async def get_zones(
    config_id: UUID,
    service: CloudflareService = Depends(get_cloudflare_service),
) -> list[Zone]:
    """Get available zones (domains) for the account.

    Returns zones that can be used for the MCP Portal hostname.
    """
    return await service.get_zones(config_id)
