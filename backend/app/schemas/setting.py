"""Pydantic schemas for Settings API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SettingResponse(BaseModel):
    """Schema for setting response.

    NOTE: Encrypted values are masked in responses.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    value: str | None  # Masked if encrypted
    encrypted: bool
    description: str | None
    updated_at: datetime


class SettingListResponse(BaseModel):
    """Schema for listing all settings."""

    settings: list[SettingResponse]
