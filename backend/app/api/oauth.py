"""OAuth 2.0 API endpoints for authorization code flow.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db, get_settings
from app.models import Credential
from app.schemas.credential import (
    OAuthCallbackRequest,
    OAuthCallbackResponse,
    OAuthProvider,
    OAuthRefreshResponse,
    OAuthStartResponse,
)
from app.services.credential import CredentialService
from app.services.oauth import (
    OAuthError,
    OAuthService,
    OAuthStateError,
    OAuthTokenError,
    get_oauth_provider,
    get_oauth_providers,
)

router = APIRouter(prefix="/oauth", tags=["oauth"])
_logger = logging.getLogger(__name__)


def _sanitize_oauth_error(error: Exception, context: str) -> str:
    """Sanitize OAuth error messages for API responses.

    Returns detailed error messages for local admin debugging.
    Detailed errors are logged server-side.
    """
    # Log full error details server-side
    _logger.error(f"OAuth error ({context}): {type(error).__name__}: {error}")

    # Return detailed error for local admin debugging
    if isinstance(error, OAuthTokenError) and error.provider_error:
        return f"{context}: {error.provider_error}"
    return f"{context}: {error}"


def get_credential_service(db: AsyncSession = Depends(get_db)) -> CredentialService:
    """Dependency to get credential service."""
    return CredentialService(db)


def get_oauth_service(db: AsyncSession = Depends(get_db)) -> OAuthService:
    """Dependency to get OAuth service."""
    settings = get_settings()
    # Build redirect URI from settings
    redirect_uri = f"{settings.backend_url}/api/oauth/callback"
    return OAuthService(db, redirect_uri)


@router.get("/providers", response_model=list[OAuthProvider])
async def list_oauth_providers():
    """List available OAuth provider presets.

    Returns common OAuth providers with their configuration URLs.
    """
    return get_oauth_providers()


@router.get("/providers/{provider_id}", response_model=OAuthProvider)
async def get_provider(provider_id: str):
    """Get OAuth provider preset by ID."""
    provider = get_oauth_provider(provider_id)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OAuth provider '{provider_id}' not found",
        )
    return provider


@router.post(
    "/credentials/{credential_id}/start",
    response_model=OAuthStartResponse,
)
async def start_oauth_flow(
    credential_id: UUID,
    credential_service: CredentialService = Depends(get_credential_service),
    oauth_service: OAuthService = Depends(get_oauth_service),
):
    """Start OAuth authorization code flow for a credential.

    Returns an authorization URL that the frontend should redirect the user to.
    The user will authenticate with the OAuth provider and be redirected back
    to the callback endpoint.
    """
    credential = await credential_service.get(credential_id)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found",
        )

    if credential.auth_type != "oauth2":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential is not OAuth2 type",
        )

    if credential.oauth_grant_type != "authorization_code":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential is not configured for authorization_code flow. "
            "Set oauth_grant_type to 'authorization_code' when creating the credential.",
        )

    try:
        auth_url, state = await oauth_service.start_authorization(credential)
    except OAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_sanitize_oauth_error(e, "Authorization start"),
        ) from None

    return OAuthStartResponse(
        authorization_url=auth_url,
        state=state,
        credential_id=credential_id,
    )


@router.get("/callback")
async def oauth_callback_redirect(
    code: str = Query(..., description="Authorization code from OAuth provider"),
    state: str = Query(..., description="State parameter for CSRF validation"),
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth callback from provider (browser redirect).

    This endpoint receives the redirect from the OAuth provider after user authorization.
    It processes the callback and redirects to the frontend with the result.

    Security: Error messages are sanitized to prevent information leakage.
    Detailed errors are logged server-side only.
    """
    app_settings = get_settings()
    redirect_uri = f"{app_settings.backend_url}/api/oauth/callback"
    oauth_service = OAuthService(db, redirect_uri)

    # Find credential by state
    result = await db.execute(select(Credential).where(Credential.oauth_state == state))
    credential = result.scalar_one_or_none()

    if not credential:
        # Redirect to frontend with generic error
        return RedirectResponse(
            url=f"{app_settings.frontend_url}/oauth/callback?error=invalid_state"
        )

    try:
        await oauth_service.handle_callback(credential, code, state)
        # Note: handle_callback() already commits internally

        # Redirect to frontend with success
        return RedirectResponse(
            url=f"{app_settings.frontend_url}/oauth/callback?success=true&credential_id={credential.id}&server_id={credential.server_id}"
        )
    except OAuthStateError:
        return RedirectResponse(
            url=f"{app_settings.frontend_url}/oauth/callback?error=invalid_state"
        )
    except OAuthTokenError as e:
        # Log the detailed error server-side only
        _logger.warning(
            f"OAuth token error for credential {credential.id}: {e.provider_error or str(e)}"
        )
        # Return generic error to client
        return RedirectResponse(url=f"{app_settings.frontend_url}/oauth/callback?error=token_error")
    except Exception as e:
        # Log the detailed error server-side only
        _logger.error(
            f"OAuth callback error for credential {credential.id}: {e!s}",
            exc_info=True,
        )
        # Return generic error to client
        return RedirectResponse(
            url=f"{app_settings.frontend_url}/oauth/callback?error=authorization_failed"
        )


@router.post(
    "/callback",
    response_model=OAuthCallbackResponse,
)
async def oauth_callback_api(
    data: OAuthCallbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth callback via API (for SPAs that handle the redirect themselves).

    This endpoint can be used by frontends that capture the OAuth callback
    and want to process it via API instead of the redirect-based flow.
    """
    settings = get_settings()
    redirect_uri = f"{settings.backend_url}/api/oauth/callback"
    oauth_service = OAuthService(db, redirect_uri)

    # Find credential by state
    result = await db.execute(select(Credential).where(Credential.oauth_state == data.state))
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )

    try:
        result = await oauth_service.handle_callback(credential, data.code, data.state)
        # Note: handle_callback() already commits internally

        return OAuthCallbackResponse(
            success=True,
            credential_id=credential.id,
            message="OAuth authorization successful",
            has_access_token=True,
            has_refresh_token=result.get("refresh_token_stored", False),
            access_token_expires_at=result.get("expires_at"),
        )
    except OAuthStateError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        ) from None
    except OAuthTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_sanitize_oauth_error(e, "Token exchange"),
        ) from None


@router.post(
    "/credentials/{credential_id}/refresh",
    response_model=OAuthRefreshResponse,
)
async def refresh_oauth_token(
    credential_id: UUID,
    credential_service: CredentialService = Depends(get_credential_service),
    oauth_service: OAuthService = Depends(get_oauth_service),
    db: AsyncSession = Depends(get_db),
):
    """Refresh an OAuth access token.

    Uses the stored refresh token to obtain a new access token.
    Only works for credentials that have a refresh token stored.
    """
    credential = await credential_service.get(credential_id)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found",
        )

    if credential.auth_type != "oauth2":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential is not OAuth2 type",
        )

    if not credential.encrypted_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential does not have a refresh token. "
            "Re-authorize to obtain a new refresh token.",
        )

    try:
        result = await oauth_service.refresh_token(credential)
        # Note: refresh_token() already commits internally

        return OAuthRefreshResponse(
            success=True,
            credential_id=credential_id,
            message="Token refreshed successfully",
            access_token_expires_at=result.get("expires_at"),
        )
    except OAuthTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_sanitize_oauth_error(e, "Token refresh"),
        ) from None
    except OAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_sanitize_oauth_error(e, "Token refresh"),
        ) from None


@router.get(
    "/credentials/{credential_id}/status",
)
async def get_oauth_token_status(
    credential_id: UUID,
    credential_service: CredentialService = Depends(get_credential_service),
    oauth_service: OAuthService = Depends(get_oauth_service),
):
    """Get OAuth token status for a credential.

    Returns information about the token's validity and expiration.
    """
    credential = await credential_service.get(credential_id)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found",
        )

    if credential.auth_type != "oauth2":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential is not OAuth2 type",
        )

    has_access_token = credential.encrypted_access_token is not None
    has_refresh_token = credential.encrypted_refresh_token is not None
    is_expired = oauth_service.is_token_expired(credential) if has_access_token else True
    flow_pending = credential.oauth_state is not None

    return {
        "credential_id": credential_id,
        "has_access_token": has_access_token,
        "has_refresh_token": has_refresh_token,
        "is_expired": is_expired,
        "expires_at": credential.access_token_expires_at,
        "flow_pending": flow_pending,
        "can_refresh": has_refresh_token and is_expired,
    }
