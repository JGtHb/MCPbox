"""Pydantic schemas for server secrets."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SecretCreate(BaseModel):
    """Schema for creating a secret placeholder (no value)."""

    key_name: str = Field(..., min_length=1, max_length=255, pattern=r"^[A-Z][A-Z0-9_]*$")
    description: str | None = Field(None, max_length=2000)


class SecretSetValue(BaseModel):
    """Schema for setting a secret value (admin only)."""

    value: str = Field(..., min_length=1)


class SecretResponse(BaseModel):
    """Schema for secret response (never includes actual value)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    server_id: UUID
    key_name: str
    description: str | None
    has_value: bool
    created_at: datetime
    updated_at: datetime


class SecretListResponse(BaseModel):
    """Paginated list of secrets."""

    items: list[SecretResponse]
    total: int
