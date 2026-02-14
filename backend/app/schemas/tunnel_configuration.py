"""Pydantic schemas for Tunnel Configuration API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TunnelConfigurationBase(BaseModel):
    """Base schema for tunnel configuration data."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Configuration name (e.g., 'Production', 'Development')",
    )
    description: str | None = Field(
        None, max_length=2000, description="Optional description for this configuration"
    )
    public_url: str | None = Field(
        None,
        max_length=1024,
        description="Public URL/hostname for this tunnel (e.g., 'mcpbox.example.com')",
    )

    @field_validator("public_url")
    @classmethod
    def validate_public_url(cls, v: str | None) -> str | None:
        """Normalize and validate the public URL."""
        if v is None or v.strip() == "":
            return None

        v = v.strip()

        # Add https:// prefix if missing
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"

        # Remove trailing slashes
        v = v.rstrip("/")

        return v


class TunnelConfigurationCreate(TunnelConfigurationBase):
    """Schema for creating a new tunnel configuration."""

    tunnel_token: str = Field(
        ..., min_length=10, description="Cloudflare tunnel token from Zero Trust Dashboard"
    )


class TunnelConfigurationUpdate(BaseModel):
    """Schema for updating a tunnel configuration."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    public_url: str | None = Field(None, max_length=1024)
    tunnel_token: str | None = Field(
        None, min_length=10, description="Update the tunnel token (leave empty to keep current)"
    )

    @field_validator("public_url")
    @classmethod
    def validate_public_url(cls, v: str | None) -> str | None:
        """Normalize and validate the public URL."""
        if v is None:
            return None

        v = v.strip()
        if v == "":
            return None

        # Add https:// prefix if missing
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"

        # Remove trailing slashes
        v = v.rstrip("/")

        return v


class TunnelConfigurationResponse(BaseModel):
    """Schema for tunnel configuration response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    public_url: str | None
    is_active: bool
    has_token: bool = Field(description="Whether a tunnel token is configured")
    created_at: datetime
    updated_at: datetime


class TunnelConfigurationListResponse(BaseModel):
    """Schema for tunnel configuration list response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    public_url: str | None
    is_active: bool
    has_token: bool
    created_at: datetime


class TunnelConfigurationListPaginatedResponse(BaseModel):
    """Schema for paginated tunnel configuration list response."""

    items: list[TunnelConfigurationListResponse]
    total: int
    page: int
    page_size: int
    pages: int


class TunnelConfigurationActivateResponse(BaseModel):
    """Response for activating a configuration."""

    message: str
    configuration: TunnelConfigurationResponse
