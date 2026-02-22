"""Pydantic schemas for Server API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ServerBase(BaseModel):
    """Base schema for server data."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)


class ServerCreate(ServerBase):
    """Schema for creating a new server.

    Inherits all fields from ServerBase without modifications.
    """


class ServerUpdate(BaseModel):
    """Schema for updating a server."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    network_mode: str | None = Field(None, pattern="^(isolated|allowlist)$")
    default_timeout_ms: int | None = Field(None, ge=1000, le=300000)
    # NOTE: allowed_modules removed - now global in Settings


class ToolSummary(BaseModel):
    """Summary of a tool for inclusion in server response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    enabled: bool


class ServerResponse(BaseModel):
    """Schema for server response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    status: str
    network_mode: str
    default_timeout_ms: int
    created_at: datetime
    updated_at: datetime
    tools: list[ToolSummary] = []
    tool_count: int = 0


class ServerListResponse(BaseModel):
    """Schema for server list response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    status: str
    network_mode: str
    tool_count: int = 0
    created_at: datetime


class ServerListPaginatedResponse(BaseModel):
    """Schema for paginated server list response."""

    items: list[ServerListResponse]
    total: int
    page: int
    page_size: int
    pages: int


# ============================================================================
# Allowed Hosts Management Schemas
# ============================================================================


class AddHostRequest(BaseModel):
    """Schema for adding a host to a server's allowlist."""

    host: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Hostname or IP address to add (e.g., 'api.github.com')",
    )


class AllowedHostsResponse(BaseModel):
    """Schema for allowed hosts response after add/remove."""

    server_id: UUID
    network_mode: str
    allowed_hosts: list[str]


# NOTE: Module configuration schemas removed.
# Module whitelist is now global - see /api/settings/modules
