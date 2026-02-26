"""Internal endpoints for service-to-service communication.

These endpoints are ONLY accessible on the Docker internal network
(backend is bound to 127.0.0.1 on the host). They are excluded from
admin auth middleware but require a Bearer token for defense-in-depth.

Two keys are accepted:
- SANDBOX_API_KEY: shared secret for backend ↔ sandbox communication
- CLOUDFLARED_API_KEY: dedicated key for cloudflared (falls back to SANDBOX_API_KEY)
"""

import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.cloudflare_config import CloudflareConfig
from app.services.crypto import decrypt_from_base64
from app.services.tunnel_configuration import TunnelConfigurationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def _extract_bearer_token(authorization: str | None) -> str:
    """Extract the Bearer token from an Authorization header."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing Authorization header",
        )
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Authorization header format",
        )
    return authorization[7:]


async def verify_internal_auth(
    authorization: str | None = Header(default=None),
) -> None:
    """Verify internal service-to-service authentication.

    Accepts either SANDBOX_API_KEY or CLOUDFLARED_API_KEY as a Bearer token.
    """
    token = _extract_bearer_token(authorization)

    expected_key = settings.sandbox_api_key
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal auth not configured",
        )

    # Accept SANDBOX_API_KEY
    if secrets.compare_digest(token.encode(), expected_key.encode()):
        return

    # Accept CLOUDFLARED_API_KEY if configured
    cloudflared_key = settings.cloudflared_api_key
    if cloudflared_key and secrets.compare_digest(token.encode(), cloudflared_key.encode()):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid internal auth token",
    )


@router.get("/active-tunnel-token")
async def get_active_tunnel_token(
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(verify_internal_auth),
) -> dict:
    """Get the decrypted token for the currently active tunnel configuration.

    Used by the cloudflared container to fetch its token at startup
    instead of reading from an environment variable.
    """
    service = TunnelConfigurationService(db)
    active_config = await service.get_active()

    if not active_config:
        return {"token": None, "error": "No active tunnel configuration"}

    token = await service.get_decrypted_token(active_config.id)

    if not token:
        return {"token": None, "error": "Active configuration has no tunnel token"}

    return {"token": token}


@router.get("/worker-deploy-config")
async def get_worker_deploy_config(
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(verify_internal_auth),
) -> dict:
    """Get configuration needed to generate wrangler.toml and deploy the Worker.

    Used by scripts/deploy-worker.sh to dynamically generate wrangler.toml
    with the correct VPC service ID instead of hardcoding it.
    """
    result = await db.execute(select(CloudflareConfig).where(CloudflareConfig.status == "active"))
    config = result.scalar_one_or_none()

    if not config:
        return {"error": "No active Cloudflare configuration"}

    if not config.vpc_service_id:
        return {"error": "VPC service not created yet (complete wizard step 3)"}

    # Decrypt OIDC credentials for Worker secrets
    access_client_id = ""
    access_client_secret = ""
    if config.encrypted_access_client_id:
        try:
            access_client_id = decrypt_from_base64(
                config.encrypted_access_client_id, aad="access_client_id"
            )
        except Exception:
            pass
    if config.encrypted_access_client_secret:
        try:
            access_client_secret = decrypt_from_base64(
                config.encrypted_access_client_secret, aad="access_client_secret"
            )
        except Exception:
            pass

    # Build OIDC endpoint URLs from team_domain and client_id
    access_token_url = ""
    access_authorization_url = ""
    access_jwks_url = ""
    if config.team_domain and access_client_id:
        base = f"https://{config.team_domain}/cdn-cgi/access/sso/oidc/{access_client_id}"
        access_token_url = f"{base}/token"
        access_authorization_url = f"{base}/authorize"
        access_jwks_url = f"https://{config.team_domain}/cdn-cgi/access/certs"

    return {
        "vpc_service_id": config.vpc_service_id,
        "worker_name": config.worker_name or "mcpbox-proxy",
        "has_service_token": config.encrypted_service_token is not None,
        "kv_namespace_id": config.kv_namespace_id,
        # Access for SaaS OIDC credentials
        "access_client_id": access_client_id,
        "access_client_secret": access_client_secret,
        "access_token_url": access_token_url,
        "access_authorization_url": access_authorization_url,
        "access_jwks_url": access_jwks_url,
    }


@router.get("/active-service-token")
async def get_active_service_token(
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(verify_internal_auth),
) -> dict:
    """Get the decrypted MCP service token for the active configuration.

    Used by scripts/deploy-worker.sh to set the MCPBOX_SERVICE_TOKEN
    Worker secret, ensuring the Worker and MCPbox share the same token.
    """
    result = await db.execute(select(CloudflareConfig).where(CloudflareConfig.status == "active"))
    config = result.scalar_one_or_none()

    if not config or not config.encrypted_service_token:
        return {"token": None, "error": "No active service token"}

    token = decrypt_from_base64(config.encrypted_service_token, aad="service_token")
    return {"token": token}
