"""Cloudflare remote access wizard API endpoints.

Provides a step-by-step wizard to configure Cloudflare remote access:
1. Login with Cloudflare OAuth
2. Create Cloudflare tunnel
3. Create VPC service for private tunnel access
4. Deploy MCPbox proxy Worker
5. Configure Worker OIDC authentication
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.cloudflare import (
    ConfigureJwtRequest,
    ConfigureJwtResponse,
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
    UpdateAccessPolicyRequest,
    UpdateAccessPolicyResponse,
    UpdateWorkerConfigRequest,
    UpdateWorkerConfigResponse,
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
    or access management. This endpoint allows setting a proper API token
    with those permissions.

    Required token permissions:
    - Account > Cloudflare Tunnel > Edit
    - Account > Access: Apps and Policies > Edit
    - Account > Workers Scripts > Edit
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
# Step 5: Configure Worker JWT
# =============================================================================


@router.post("/worker-jwt-config", response_model=ConfigureJwtResponse)
async def configure_worker_jwt(
    request: ConfigureJwtRequest,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> ConfigureJwtResponse:
    """Configure Worker OIDC authentication (step 5).

    Creates a SaaS OIDC Access Application (if not already created),
    applies the Access Policy, and syncs OIDC secrets to the Worker.
    After this step, the Worker URL can be used directly by MCP clients.
    """
    try:
        result = await service.configure_worker_jwt(
            request.config_id, access_policy=request.access_policy
        )
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    except Exception:
        logger.exception("Failed to configure Worker OIDC")
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to configure Worker OIDC. Check server logs for details.",
        ) from None


# =============================================================================
# Update Access Policy
# =============================================================================


@router.put("/access-policy", response_model=UpdateAccessPolicyResponse)
async def update_access_policy(
    request: UpdateAccessPolicyRequest,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> UpdateAccessPolicyResponse:
    """Update the access policy for the Cloudflare Access SaaS application.

    Syncs the allowed emails/domain to the Cloudflare Access Policy on the
    SaaS OIDC Access Application. The Access Policy at the OIDC layer is
    the single source of truth for email enforcement.
    """
    try:
        result = await service.update_access_policy(
            request.config_id,
            request.access_policy,
        )
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
# Teardown
# =============================================================================


@router.delete("/teardown/{config_id}", response_model=TeardownResponse)
async def teardown(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> TeardownResponse:
    """Remove all Cloudflare resources created by the wizard.

    Deletes the OIDC Access Application, Worker, KV namespace, VPC Service, and Tunnel.
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
# Worker Configuration (CORS + Redirect URIs)
# =============================================================================


@router.put("/worker-config", response_model=UpdateWorkerConfigResponse)
async def update_worker_config(
    request: UpdateWorkerConfigRequest,
    db: AsyncSession = Depends(get_db),
    service: CloudflareService = Depends(get_cloudflare_service),
) -> UpdateWorkerConfigResponse:
    """Update Worker CORS origins and OAuth redirect URIs.

    Saves the configuration to the database and syncs it to the Worker's
    KV namespace so the Worker picks it up immediately without redeployment.
    Built-in origins (Claude, ChatGPT, OpenAI, Cloudflare, localhost) are
    always included by the Worker — these are *additional* origins.
    """
    try:
        result = await service.update_worker_config(
            request.config_id,
            allowed_cors_origins=request.allowed_cors_origins,
            allowed_redirect_uris=request.allowed_redirect_uris,
        )
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


@router.get("/worker-config/{config_id}", response_model=UpdateWorkerConfigResponse)
async def get_worker_config(
    config_id: UUID,
    service: CloudflareService = Depends(get_cloudflare_service),
) -> UpdateWorkerConfigResponse:
    """Get current Worker CORS origins and redirect URI configuration."""
    try:
        return await service.get_worker_config(config_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None


# =============================================================================
# Get Zones
# =============================================================================


@router.get("/zones/{config_id}")
async def get_zones(
    config_id: UUID,
    service: CloudflareService = Depends(get_cloudflare_service),
) -> list[Zone]:
    """Get available zones (domains) for the account.

    Returns zones that can be used for the Worker hostname.
    """
    return await service.get_zones(config_id)
