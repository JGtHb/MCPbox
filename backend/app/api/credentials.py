"""Credential API endpoints.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.core.request_utils import get_client_ip
from app.schemas.credential import (
    CredentialCreate,
    CredentialListPaginatedResponse,
    CredentialListResponse,
    CredentialResponse,
    CredentialUpdate,
    TokenStatus,
)
from app.services.audit import AuditService, get_audit_service
from app.services.credential import CredentialService
from app.services.server import ServerService

router = APIRouter(tags=["credentials"])


def get_credential_service(db: AsyncSession = Depends(get_db)) -> CredentialService:
    """Dependency to get credential service."""
    return CredentialService(db)


def get_server_service(db: AsyncSession = Depends(get_db)) -> ServerService:
    """Dependency to get server service."""
    return ServerService(db)


@router.post(
    "/servers/{server_id}/credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_credential(
    server_id: UUID,
    data: CredentialCreate,
    request: Request,
    credential_service: CredentialService = Depends(get_credential_service),
    server_service: ServerService = Depends(get_server_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> CredentialResponse:
    """Create a new credential for a server.

    Sensitive values (value, password, tokens) are encrypted at rest.
    """
    # Verify server exists
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    credential = await credential_service.create(server_id, data)

    # Audit log
    await audit_service.log_credential_create(
        credential_id=credential.id,
        server_id=server_id,
        credential_name=credential.name,
        auth_type=credential.auth_type,
        actor_ip=get_client_ip(request),
    )

    return _to_response(credential)


@router.get("/servers/{server_id}/credentials", response_model=CredentialListPaginatedResponse)
async def list_credentials(
    server_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    credential_service: CredentialService = Depends(get_credential_service),
    server_service: ServerService = Depends(get_server_service),
) -> CredentialListPaginatedResponse:
    """List all credentials for a server with pagination.

    Note: Sensitive values are never returned in responses.
    """
    # Verify server exists
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found",
        )

    credentials, total = await credential_service.list_by_server(
        server_id, page=page, page_size=page_size
    )
    items = [
        CredentialListResponse(
            id=c.id,
            name=c.name,
            auth_type=c.auth_type,
            description=c.description,
        )
        for c in credentials
    ]
    pages = (total + page_size - 1) // page_size if total > 0 else 0
    return CredentialListPaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/credentials/{credential_id}", response_model=CredentialResponse)
async def get_credential(
    credential_id: UUID,
    credential_service: CredentialService = Depends(get_credential_service),
) -> CredentialResponse:
    """Get a credential by ID.

    Note: Sensitive values are never returned in responses.
    """
    credential = await credential_service.get(credential_id)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found",
        )
    return _to_response(credential)


@router.patch("/credentials/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: UUID,
    data: CredentialUpdate,
    request: Request,
    credential_service: CredentialService = Depends(get_credential_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> CredentialResponse:
    """Update a credential.

    Sensitive values can be updated; they will be re-encrypted.
    """
    # Get existing credential for audit
    existing = await credential_service.get(credential_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found",
        )

    credential = await credential_service.update(credential_id, data)

    # Audit log with changes - sanitize to avoid logging secrets
    changes = data.model_dump(exclude_unset=True)
    # Redact sensitive fields before logging
    sensitive_fields = {
        "value",
        "password",
        "client_secret",
        "access_token",
        "refresh_token",
        "private_key",
        "username",
    }
    sanitized_changes = {
        k: "[REDACTED]" if k in sensitive_fields else v for k, v in changes.items()
    }
    await audit_service.log_credential_update(
        credential_id=credential_id,
        server_id=credential.server_id if credential else None,
        changes=sanitized_changes,
        actor_ip=get_client_ip(request),
    )

    return _to_response(credential)


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: UUID,
    request: Request,
    credential_service: CredentialService = Depends(get_credential_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> None:
    """Delete a credential."""
    # Get credential info for audit before deletion
    credential = await credential_service.get(credential_id)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found",
        )

    credential_name = credential.name
    server_id = credential.server_id

    deleted = await credential_service.delete(credential_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found",
        )

    # Audit log
    await audit_service.log_credential_delete(
        credential_id=credential_id,
        credential_name=credential_name,
        server_id=server_id,
        actor_ip=get_client_ip(request),
    )

    return None


def _calculate_token_status(credential: Any) -> tuple[TokenStatus | None, int | None]:
    """Calculate OAuth token status based on expiration time.

    Returns:
        Tuple of (status, expires_in_seconds)
    """
    if credential.auth_type != "oauth2":
        return None, None

    if credential.encrypted_access_token is None:
        return "not_configured", None

    if credential.access_token_expires_at is None:
        # Token exists but no expiration - assume valid
        return "valid", None

    now = datetime.now(UTC)
    expires_at = credential.access_token_expires_at

    # Ensure timezone awareness
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    expires_in = int((expires_at - now).total_seconds())

    if expires_in <= 0:
        return "expired", 0
    elif expires_in < 300:  # Less than 5 minutes
        return "expiring_soon", expires_in
    else:
        return "valid", expires_in


def _to_response(credential: Any) -> CredentialResponse:
    """Convert credential model to response schema.

    IMPORTANT: Never include decrypted sensitive values in responses.
    We indicate presence of encrypted values with has_* fields.
    """
    token_status, expires_in = _calculate_token_status(credential)

    return CredentialResponse(
        id=credential.id,
        server_id=credential.server_id,
        name=credential.name,
        description=credential.description,
        auth_type=credential.auth_type,
        header_name=credential.header_name,
        query_param_name=credential.query_param_name,
        oauth_client_id=credential.oauth_client_id,
        oauth_token_url=credential.oauth_token_url,
        oauth_scopes=credential.oauth_scopes,
        access_token_expires_at=credential.access_token_expires_at,
        oauth_grant_type=credential.oauth_grant_type,
        oauth_authorization_url=credential.oauth_authorization_url,
        oauth_flow_pending=credential.oauth_state is not None,
        has_value=credential.encrypted_value is not None,
        has_username=credential.encrypted_username is not None,
        has_password=credential.encrypted_password is not None,
        has_access_token=credential.encrypted_access_token is not None,
        has_refresh_token=credential.encrypted_refresh_token is not None,
        token_status=token_status,
        token_expires_in_seconds=expires_in,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )
