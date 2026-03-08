"""Shared API dependencies.

Centralizes service factory functions and common utilities
used across multiple API route modules.
"""

from typing import TypeVar
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.services.approval import ApprovalService
from app.services.auth import AuthService
from app.services.cloudflare import CloudflareService
from app.services.external_mcp_source import ExternalMCPSourceService
from app.services.global_config import GlobalConfigService
from app.services.server import ServerService
from app.services.server_secret import ServerSecretService
from app.services.setting import SettingService
from app.services.tool import ToolService

# ---------------------------------------------------------------------------
# Service factory dependencies (for use with FastAPI Depends())
# ---------------------------------------------------------------------------


def get_server_service(db: AsyncSession = Depends(get_db)) -> ServerService:
    """Dependency to get server service."""
    return ServerService(db)


def get_tool_service(db: AsyncSession = Depends(get_db)) -> ToolService:
    """Dependency to get tool service."""
    return ToolService(db)


def get_approval_service(db: AsyncSession = Depends(get_db)) -> ApprovalService:
    """Dependency to get approval service."""
    return ApprovalService(db)


def get_setting_service(db: AsyncSession = Depends(get_db)) -> SettingService:
    """Dependency to get setting service."""
    return SettingService(db)


def get_global_config_service(db: AsyncSession = Depends(get_db)) -> GlobalConfigService:
    """Dependency to get global config service."""
    return GlobalConfigService(db)


def get_secret_service(db: AsyncSession = Depends(get_db)) -> ServerSecretService:
    """Dependency to get server secret service."""
    return ServerSecretService(db)


def get_source_service(db: AsyncSession = Depends(get_db)) -> ExternalMCPSourceService:
    """Dependency to get external MCP source service."""
    return ExternalMCPSourceService(db)


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    """Dependency to get auth service."""
    return AuthService(db)


def get_cloudflare_service(db: AsyncSession = Depends(get_db)) -> CloudflareService:
    """Dependency to get Cloudflare service."""
    return CloudflareService(db)


# ---------------------------------------------------------------------------
# Common utilities
# ---------------------------------------------------------------------------


def calc_pages(total: int, page_size: int) -> int:
    """Calculate total page count for pagination."""
    return (total + page_size - 1) // page_size if total > 0 else 0


_T = TypeVar("_T")


def require_found(obj: _T | None, resource: str, resource_id: UUID | str | int) -> _T:
    """Raise 404 if *obj* is None, otherwise return it (narrowing the type)."""
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} {resource_id} not found",
        )
    return obj
