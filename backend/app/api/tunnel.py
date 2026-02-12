"""Tunnel API endpoints - Cloudflare tunnel management.

Only supports named tunnels with Cloudflare MCP Server Portals for authentication.
Quick/temporary tunnels have been removed as they require the same Cloudflare
setup but provide a less stable URL.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.request_utils import get_client_ip
from app.schemas.tunnel_configuration import (
    TunnelConfigurationActivateResponse,
    TunnelConfigurationCreate,
    TunnelConfigurationListPaginatedResponse,
    TunnelConfigurationResponse,
    TunnelConfigurationUpdate,
)
from app.services.audit import AuditAction, AuditService, get_audit_service
from app.services.tunnel import TunnelService, get_tunnel_service
from app.services.tunnel_configuration import TunnelConfigurationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tunnel", tags=["tunnel"])


class TunnelStatusResponse(BaseModel):
    """Response model for tunnel status."""

    status: str  # disconnected, connecting, connected, error
    url: str | None = None
    started_at: str | None = None
    error: str | None = None


class TunnelStartResponse(BaseModel):
    """Response model for tunnel start."""

    status: str
    url: str | None = None
    started_at: str | None = None
    error: str | None = None


@router.get("/status", response_model=TunnelStatusResponse)
async def get_tunnel_status(
    tunnel_service: TunnelService = Depends(get_tunnel_service),
) -> TunnelStatusResponse:
    """Get current tunnel status.

    Returns connection status and URL (if connected).
    """
    # Do a health check to update status
    await tunnel_service.health_check()

    status_dict = tunnel_service.get_status()
    return TunnelStatusResponse(**status_dict)


@router.post("/start", response_model=TunnelStartResponse)
async def start_tunnel(
    http_request: Request,
    tunnel_service: TunnelService = Depends(get_tunnel_service),
    db: AsyncSession = Depends(get_db),
    audit_service: AuditService = Depends(get_audit_service),
) -> TunnelStartResponse:
    """Start the Cloudflare tunnel using the active configuration.

    Requires an active tunnel configuration with a valid Cloudflare tunnel token.
    Authentication is handled by Cloudflare MCP Server Portals.

    Returns the public URL once connected.
    """
    try:
        config_service = TunnelConfigurationService(db)

        # Get active configuration
        active_config = await config_service.get_active()

        if not active_config:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active tunnel configuration. Create and activate a configuration first.",
            )

        # Get the tunnel token
        tunnel_token = await config_service.get_decrypted_token(active_config.id)
        tunnel_url = active_config.public_url
        config_name = active_config.name

        if not tunnel_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Active configuration is missing tunnel token.",
            )

        result = await tunnel_service.start(
            tunnel_token=tunnel_token,
            named_tunnel_url=tunnel_url,
        )

        # Audit log
        await audit_service.log_tunnel_action(
            action=AuditAction.TUNNEL_START,
            details={
                "url": result.get("url"),
                "configuration": config_name,
            },
            actor_ip=get_client_ip(http_request),
        )

        return TunnelStartResponse(**result)

    except RuntimeError as e:
        logger.warning(f"Tunnel start failed (RuntimeError): {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to start tunnel. Check tunnel configuration.",
        ) from None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to start tunnel: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while starting the tunnel.",
        ) from e


@router.post("/stop", response_model=TunnelStatusResponse)
async def stop_tunnel(
    http_request: Request,
    tunnel_service: TunnelService = Depends(get_tunnel_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> TunnelStatusResponse:
    """Stop the Cloudflare tunnel.

    Gracefully stops the cloudflared process.
    """
    try:
        result = await tunnel_service.stop()

        # Audit log
        await audit_service.log_tunnel_action(
            action=AuditAction.TUNNEL_STOP,
            actor_ip=get_client_ip(http_request),
        )

        return TunnelStatusResponse(**result)
    except Exception as e:
        logger.exception(f"Failed to stop tunnel: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while stopping the tunnel.",
        ) from e


# =============================================================================
# Named Tunnel Configuration Management Endpoints
# =============================================================================


@router.get("/configurations", response_model=TunnelConfigurationListPaginatedResponse)
async def list_tunnel_configurations(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> TunnelConfigurationListPaginatedResponse:
    """List all saved tunnel configurations.

    Returns paginated list of tunnel profiles that can be activated.
    """
    service = TunnelConfigurationService(db)
    return await service.list(page=page, page_size=page_size)


@router.post(
    "/configurations",
    response_model=TunnelConfigurationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tunnel_configuration(
    config: TunnelConfigurationCreate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    audit_service: AuditService = Depends(get_audit_service),
) -> TunnelConfigurationResponse:
    """Create a new tunnel configuration.

    Creates a new named tunnel profile. The configuration is NOT automatically
    activated - use the activate endpoint to switch to it.
    """
    service = TunnelConfigurationService(db)

    try:
        created = await service.create(config)
        await db.commit()

        # Audit log
        await audit_service.log_tunnel_action(
            action=AuditAction.TUNNEL_CONFIG_UPDATE,
            details={
                "action": "create_configuration",
                "configuration_id": str(created.id),
                "name": created.name,
            },
            actor_ip=get_client_ip(http_request),
        )

        response = await service.get_response(created.id)
        if not response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Configuration not found after creation",
            )
        return response
    except ValueError as e:
        # ValueError from service validation (e.g., duplicate name)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    except Exception as e:
        logger.exception(f"Failed to create tunnel configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while creating the configuration.",
        ) from e


@router.get("/configurations/{config_id}", response_model=TunnelConfigurationResponse)
async def get_tunnel_configuration(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> TunnelConfigurationResponse:
    """Get a tunnel configuration by ID."""
    service = TunnelConfigurationService(db)
    response = await service.get_response(config_id)

    if not response:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tunnel configuration not found",
        )

    return response


@router.put("/configurations/{config_id}", response_model=TunnelConfigurationResponse)
async def update_tunnel_configuration(
    config_id: UUID,
    config: TunnelConfigurationUpdate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    audit_service: AuditService = Depends(get_audit_service),
) -> TunnelConfigurationResponse | None:
    """Update a tunnel configuration.

    Updates the specified tunnel profile. If this is the active configuration,
    changes will take effect on the next tunnel restart.
    """
    service = TunnelConfigurationService(db)

    updated = await service.update(config_id, config)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tunnel configuration not found",
        )

    await db.commit()

    # Audit log
    await audit_service.log_tunnel_action(
        action=AuditAction.TUNNEL_CONFIG_UPDATE,
        details={
            "action": "update_configuration",
            "configuration_id": str(config_id),
            "name": updated.name,
            "token_updated": config.tunnel_token is not None,
        },
        actor_ip=get_client_ip(http_request),
    )

    return await service.get_response(config_id)


@router.delete("/configurations/{config_id}")
async def delete_tunnel_configuration(
    config_id: UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    audit_service: AuditService = Depends(get_audit_service),
) -> dict[str, Any]:
    """Delete a tunnel configuration.

    Cannot delete the currently active configuration.
    """
    service = TunnelConfigurationService(db)

    # Get the config first for audit logging
    config = await service.get(config_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tunnel configuration not found",
        )

    try:
        await service.delete(config_id)
        await db.commit()

        # Audit log
        await audit_service.log_tunnel_action(
            action=AuditAction.TUNNEL_CONFIG_UPDATE,
            details={
                "action": "delete_configuration",
                "configuration_id": str(config_id),
                "name": config.name,
            },
            actor_ip=get_client_ip(http_request),
        )

        return {"message": f"Tunnel configuration '{config.name}' deleted"}
    except ValueError as e:
        # ValueError from service validation (e.g., cannot delete active config)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    except Exception as e:
        logger.exception(f"Failed to delete tunnel configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while deleting the configuration.",
        ) from e


@router.post(
    "/configurations/{config_id}/activate", response_model=TunnelConfigurationActivateResponse
)
async def activate_tunnel_configuration(
    config_id: UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    audit_service: AuditService = Depends(get_audit_service),
) -> TunnelConfigurationActivateResponse:
    """Activate a tunnel configuration.

    Sets this configuration as the active one (deactivates all others).
    If tunnel is currently running, it must be restarted for changes to take effect.
    """
    service = TunnelConfigurationService(db)

    activated = await service.activate(config_id)
    if not activated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tunnel configuration not found",
        )

    await db.commit()

    # Audit log
    await audit_service.log_tunnel_action(
        action=AuditAction.TUNNEL_CONFIG_UPDATE,
        details={
            "action": "activate_configuration",
            "configuration_id": str(config_id),
            "name": activated.name,
        },
        actor_ip=get_client_ip(http_request),
    )

    response = await service.get_response(config_id)
    if not response:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tunnel configuration not found after activation",
        )
    return TunnelConfigurationActivateResponse(
        message=f"Activated configuration '{activated.name}'. Restart tunnel for changes to take effect.",
        configuration=response,
    )


@router.get("/configurations/active/current", response_model=TunnelConfigurationResponse | None)
async def get_active_configuration(
    db: AsyncSession = Depends(get_db),
) -> TunnelConfigurationResponse | None:
    """Get the currently active tunnel configuration.

    Returns null if no configuration is active.
    """
    service = TunnelConfigurationService(db)
    active = await service.get_active()

    if not active:
        return None

    return await service.get_response(active.id)
