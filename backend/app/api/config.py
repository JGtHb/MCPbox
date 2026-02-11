"""Configuration endpoint for frontend.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core import settings

router = APIRouter(
    prefix="/config",
    tags=["config"],
)


class AppConfig(BaseModel):
    """Non-sensitive application configuration for frontend."""

    app_name: str
    app_version: str


@router.get("", response_model=AppConfig)
async def get_config() -> AppConfig:
    """
    Get application configuration.

    Returns non-sensitive configuration that the frontend needs
    to display version info, etc.
    """
    return AppConfig(
        app_name=settings.app_name,
        app_version=settings.app_version,
    )
