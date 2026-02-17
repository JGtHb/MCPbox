"""Admin REST API for managing server secrets."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.server_secret import (
    SecretCreate,
    SecretListResponse,
    SecretResponse,
    SecretSetValue,
)
from app.services.sandbox_client import get_sandbox_client
from app.services.server import ServerService
from app.services.server_secret import ServerSecretService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/servers/{server_id}/secrets",
    tags=["secrets"],
)


def get_secret_service(db: AsyncSession = Depends(get_db)) -> ServerSecretService:
    return ServerSecretService(db)


def get_server_service(db: AsyncSession = Depends(get_db)) -> ServerService:
    return ServerService(db)


async def _sync_secrets_to_sandbox(
    server_id: UUID,
    service: ServerSecretService,
    server_service: ServerService,
) -> None:
    """Sync all decrypted secrets to the sandbox if the server is running.

    Called after a secret is set, updated, or deleted so the sandbox
    always has the latest values without requiring a server restart.
    """
    server = await server_service.get(server_id)
    if not server or server.status != "running":
        return

    secrets = await service.get_decrypted_for_injection(server_id)
    sandbox = get_sandbox_client()
    result = await sandbox.update_server_secrets(str(server_id), secrets)
    if not result.get("success"):
        logger.warning(
            f"Failed to sync secrets to sandbox for server {server_id}: "
            f"{result.get('error', 'unknown error')}"
        )


@router.get("", response_model=SecretListResponse)
async def list_secrets(
    server_id: UUID,
    service: ServerSecretService = Depends(get_secret_service),
    server_service: ServerService = Depends(get_server_service),
) -> SecretListResponse:
    """List all secrets for a server (values never exposed)."""
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(status_code=404, detail=f"Server {server_id} not found")

    secrets = await service.list_by_server(server_id)
    return SecretListResponse(
        items=[
            SecretResponse(
                id=s.id,
                server_id=s.server_id,
                key_name=s.key_name,
                description=s.description,
                has_value=s.has_value,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in secrets
        ],
        total=len(secrets),
    )


@router.post("", response_model=SecretResponse, status_code=201)
async def create_secret(
    server_id: UUID,
    data: SecretCreate,
    service: ServerSecretService = Depends(get_secret_service),
    server_service: ServerService = Depends(get_server_service),
) -> SecretResponse:
    """Create an empty secret placeholder."""
    server = await server_service.get(server_id)
    if not server:
        raise HTTPException(status_code=404, detail=f"Server {server_id} not found")

    try:
        secret = await service.create(
            server_id=server_id,
            key_name=data.key_name,
            description=data.description,
        )
        return SecretResponse(
            id=secret.id,
            server_id=secret.server_id,
            key_name=secret.key_name,
            description=secret.description,
            has_value=secret.has_value,
            created_at=secret.created_at,
            updated_at=secret.updated_at,
        )
    except Exception as e:
        if "uq_server_secrets_server_key" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"Secret '{data.key_name}' already exists for this server",
            ) from e
        raise


@router.put("/{key_name}", response_model=SecretResponse)
async def set_secret_value(
    server_id: UUID,
    key_name: str,
    data: SecretSetValue,
    service: ServerSecretService = Depends(get_secret_service),
    server_service: ServerService = Depends(get_server_service),
) -> SecretResponse:
    """Set or update a secret value (admin only)."""
    secret = await service.set_value(
        server_id=server_id,
        key_name=key_name,
        value=data.value,
    )
    if not secret:
        raise HTTPException(
            status_code=404,
            detail=f"Secret '{key_name}' not found for server {server_id}",
        )

    # Sync updated secrets to the sandbox so running tools see the new value
    await _sync_secrets_to_sandbox(server_id, service, server_service)

    return SecretResponse(
        id=secret.id,
        server_id=secret.server_id,
        key_name=secret.key_name,
        description=secret.description,
        has_value=secret.has_value,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.delete("/{key_name}", status_code=204)
async def delete_secret(
    server_id: UUID,
    key_name: str,
    service: ServerSecretService = Depends(get_secret_service),
    server_service: ServerService = Depends(get_server_service),
) -> None:
    """Delete a secret."""
    deleted = await service.delete(server_id=server_id, key_name=key_name)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Secret '{key_name}' not found for server {server_id}",
        )

    # Sync remaining secrets to the sandbox so the deleted key is removed
    await _sync_secrets_to_sandbox(server_id, service, server_service)

    return None
