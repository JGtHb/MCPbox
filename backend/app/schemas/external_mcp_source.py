"""Pydantic schemas for External MCP Source API."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExternalMCPAuthType(StrEnum):
    NONE = "none"
    BEARER = "bearer"
    HEADER = "header"
    OAUTH = "oauth"


class ExternalMCPTransportType(StrEnum):
    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"


class ExternalMCPSourceStatus(StrEnum):
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


class ExternalMCPSourceCreate(BaseModel):
    """Schema for creating an external MCP source."""

    name: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., min_length=1, max_length=2000)
    auth_type: ExternalMCPAuthType = ExternalMCPAuthType.NONE
    auth_secret_name: str | None = Field(None, max_length=255)
    auth_header_name: str | None = Field(None, max_length=255)
    transport_type: ExternalMCPTransportType = ExternalMCPTransportType.STREAMABLE_HTTP


class ExternalMCPSourceUpdate(BaseModel):
    """Schema for updating an external MCP source."""

    name: str | None = Field(None, min_length=1, max_length=255)
    url: str | None = Field(None, min_length=1, max_length=2000)
    auth_type: ExternalMCPAuthType | None = None
    auth_secret_name: str | None = Field(None, max_length=255)
    auth_header_name: str | None = Field(None, max_length=255)
    transport_type: ExternalMCPTransportType | None = None
    status: ExternalMCPSourceStatus | None = None


class ExternalMCPSourceResponse(BaseModel):
    """Schema for external MCP source response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    server_id: UUID
    name: str
    url: str
    auth_type: str
    auth_secret_name: str | None
    auth_header_name: str | None
    transport_type: str
    status: str
    last_discovered_at: datetime | None
    tool_count: int
    created_at: datetime
    updated_at: datetime
    # OAuth fields (tokens never exposed, only metadata)
    oauth_issuer: str | None = None
    oauth_client_id: str | None = None
    oauth_authenticated: bool = False


class DiscoveredTool(BaseModel):
    """A tool discovered from an external MCP server."""

    name: str
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    already_imported: bool = False


class DiscoverToolsResponse(BaseModel):
    """Response from tool discovery."""

    source_id: UUID
    source_name: str
    tools: list[DiscoveredTool]
    total: int


class ImportToolsRequest(BaseModel):
    """Request to import specific tools from an external MCP source."""

    tool_names: list[str] = Field(..., min_length=1)


class ImportToolResult(BaseModel):
    """Result for a single tool in an import operation."""

    name: str
    status: str  # "created", "skipped_conflict", "skipped_not_found"
    tool_id: UUID | None = None
    reason: str | None = None


class ImportToolsResponse(BaseModel):
    """Response from importing tools with detailed skip information."""

    created: list[ImportToolResult]
    skipped: list[ImportToolResult]
    total_requested: int
    total_created: int
    total_skipped: int


class OAuthStartRequest(BaseModel):
    """Request to start OAuth flow for an external MCP source."""

    callback_url: str = Field(..., min_length=1, max_length=2000)


class OAuthStartResponse(BaseModel):
    """Response with authorization URL for browser popup."""

    auth_url: str
    issuer: str


class OAuthExchangeRequest(BaseModel):
    """Request to exchange OAuth authorization code for tokens."""

    state: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)


class HealthCheckResponse(BaseModel):
    """Response from external MCP server health check."""

    source_id: UUID
    source_name: str
    healthy: bool
    latency_ms: int = 0
    error: str | None = None
