"""Pydantic schemas for Cloudflare remote access wizard API."""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_resource_name(v: str) -> str:
    """Validate Cloudflare resource names to prevent injection attacks.

    Only allows alphanumeric characters, hyphens, and underscores.
    This prevents TOML injection, log injection, and URL manipulation.
    """
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", v):
        raise ValueError(
            "Name must start with a letter or digit and contain only "
            "alphanumeric characters, hyphens, and underscores"
        )
    return v


# =============================================================================
# Shared Types
# =============================================================================

AccessPolicyType = Literal["everyone", "emails", "email_domain"]


class ExistingResource(BaseModel):
    """An existing Cloudflare resource that would be overwritten."""

    resource_type: str  # "tunnel", "vpc_service", "mcp_server", "access_app", "mcp_portal"
    name: str
    id: str


class AccessPolicyConfig(BaseModel):
    """Configuration for Cloudflare Access Policy rules."""

    policy_type: AccessPolicyType = Field(
        default="everyone",
        description="Type of access policy: everyone, emails, or email_domain",
    )
    emails: list[str] = Field(
        default_factory=list,
        description="Allowed email addresses (used when policy_type is 'emails')",
    )
    email_domain: str | None = Field(
        default=None,
        description="Allowed email domain, e.g. 'company.com' (used when policy_type is 'email_domain')",
    )


# =============================================================================
# Step 1: API Token Authentication
# =============================================================================


class Zone(BaseModel):
    """Cloudflare zone (domain) info."""

    id: str
    name: str


class StartWithApiTokenRequest(BaseModel):
    """Request to start the wizard with an API token."""

    api_token: str = Field(
        ...,
        min_length=40,
        description="Cloudflare API token with tunnel, workers, and MCP permissions",
    )


class StartWithApiTokenResponse(BaseModel):
    """Response from starting with API token."""

    success: bool
    config_id: UUID | None = None
    account_id: str | None = None
    account_name: str | None = None
    team_domain: str | None = None
    zones: list[Zone] = Field(default_factory=list)
    message: str | None = None
    error: str | None = None


class SetApiTokenRequest(BaseModel):
    """Request to set an API token for operations requiring higher permissions."""

    config_id: UUID
    api_token: str = Field(
        ...,
        min_length=40,
        description="Cloudflare API token with tunnel and MCP permissions",
    )


class SetApiTokenResponse(BaseModel):
    """Response from setting API token."""

    success: bool
    message: str | None = None


# =============================================================================
# Step 2: Create Tunnel
# =============================================================================


class CreateTunnelRequest(BaseModel):
    """Request to create a Cloudflare tunnel."""

    config_id: UUID
    name: str = Field(
        default="mcpbox-tunnel",
        min_length=1,
        max_length=63,
        description="Tunnel name",
    )
    force: bool = Field(default=False, description="If true, overwrite existing resources")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_resource_name(v)


class CreateTunnelResponse(BaseModel):
    """Response from tunnel creation."""

    success: bool
    tunnel_id: str
    tunnel_name: str
    tunnel_token: str = Field(
        description="Tunnel connector token - stored in database, used automatically by cloudflared container"
    )
    message: str | None = None


# =============================================================================
# Step 3: Create VPC Service
# =============================================================================


class CreateVpcServiceRequest(BaseModel):
    """Request to create a VPC service for the tunnel."""

    config_id: UUID
    name: str = Field(
        default="mcpbox-service",
        min_length=1,
        max_length=63,
        description="VPC service name",
    )
    force: bool = Field(default=False, description="If true, overwrite existing resources")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_resource_name(v)


class CreateVpcServiceResponse(BaseModel):
    """Response from VPC service creation."""

    success: bool
    vpc_service_id: str
    vpc_service_name: str
    message: str | None = None


# =============================================================================
# Step 4: Deploy Worker
# =============================================================================


class DeployWorkerRequest(BaseModel):
    """Request to deploy the MCPbox proxy Worker."""

    config_id: UUID
    name: str = Field(
        default="mcpbox-proxy",
        min_length=1,
        max_length=63,
        description="Worker name",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_resource_name(v)


class DeployWorkerResponse(BaseModel):
    """Response from Worker deployment."""

    success: bool
    worker_name: str
    worker_url: str = Field(description="Worker URL (e.g., mcpbox-proxy.you.workers.dev)")
    service_token: str | None = Field(
        None,
        description="Generated service token - stored in database, pushed to Worker by deploy script",
    )
    message: str | None = None


# =============================================================================
# Step 5: Create MCP Server
# =============================================================================


class CreateMcpServerRequest(BaseModel):
    """Request to create an MCP Server."""

    config_id: UUID
    server_id: str = Field(
        default="mcpbox",
        min_length=1,
        max_length=63,
        description="MCP Server ID",
    )
    server_name: str = Field(
        default="MCPbox",
        min_length=1,
        max_length=63,
        description="MCP Server display name",
    )
    force: bool = Field(default=False, description="If true, overwrite existing resources")

    @field_validator("server_id")
    @classmethod
    def validate_server_id(cls, v: str) -> str:
        return _validate_resource_name(v)

    access_policy: AccessPolicyConfig | None = Field(
        default=None,
        description="Access policy configuration. Defaults to 'everyone' if not provided.",
    )


class CreateMcpServerResponse(BaseModel):
    """Response from MCP Server creation."""

    success: bool
    mcp_server_id: str
    tools_synced: int = Field(
        default=0,
        description="Number of tools discovered during sync",
    )
    message: str | None = None


# =============================================================================
# Step 6: Create MCP Portal
# =============================================================================


class CreateMcpPortalRequest(BaseModel):
    """Request to create an MCP Portal."""

    config_id: UUID
    portal_id: str = Field(
        default="mcpbox-portal",
        min_length=1,
        max_length=63,
        description="MCP Portal ID",
    )
    portal_name: str = Field(
        default="MCPbox Portal",
        min_length=1,
        max_length=63,
        description="MCP Portal display name",
    )
    force: bool = Field(default=False, description="If true, overwrite existing resources")

    @field_validator("portal_id")
    @classmethod
    def validate_portal_id(cls, v: str) -> str:
        return _validate_resource_name(v)

    hostname: str = Field(
        ...,
        min_length=1,
        description="Portal hostname (e.g., 'mcp.yourdomain.com' or just 'yourdomain.com')",
    )
    access_policy: AccessPolicyConfig | None = Field(
        default=None,
        description="Access policy configuration. Defaults to 'everyone' if not provided.",
    )


class CreateMcpPortalResponse(BaseModel):
    """Response from MCP Portal creation."""

    success: bool
    mcp_portal_id: str
    mcp_portal_hostname: str
    portal_url: str = Field(description="Full portal URL for Claude Web")
    mcp_portal_aud: str = Field(description="Application Audience Tag for JWT verification")
    message: str | None = None


# =============================================================================
# Step 7: Configure Worker JWT
# =============================================================================


class ConfigureJwtRequest(BaseModel):
    """Request to configure Worker JWT verification."""

    config_id: UUID
    aud: str | None = Field(
        default=None,
        description="Application Audience Tag. If not provided, will attempt to fetch from API.",
    )


class ConfigureJwtResponse(BaseModel):
    """Response from Worker JWT configuration."""

    success: bool
    team_domain: str
    aud: str
    worker_test_result: str = Field(
        description="Result of testing direct Worker access (should be 401)"
    )
    message: str | None = None


# =============================================================================
# Status & Management
# =============================================================================


class WizardStatusResponse(BaseModel):
    """Current wizard status and configuration."""

    model_config = ConfigDict(from_attributes=True)

    config_id: UUID | None = None
    status: str = Field(default="not_started", description="pending, active, error, not_started")
    completed_step: int = Field(default=0, description="Last completed step (0-7)")
    error_message: str | None = None

    # Account info
    account_id: str | None = None
    account_name: str | None = None
    team_domain: str | None = None

    # Tunnel info
    tunnel_id: str | None = None
    tunnel_name: str | None = None
    has_tunnel_token: bool = False

    # VPC Service info
    vpc_service_id: str | None = None
    vpc_service_name: str | None = None

    # Worker info
    worker_name: str | None = None
    worker_url: str | None = None

    # MCP Server info
    mcp_server_id: str | None = None

    # MCP Portal info
    mcp_portal_id: str | None = None
    mcp_portal_hostname: str | None = None
    mcp_portal_aud: str | None = None

    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TeardownResponse(BaseModel):
    """Response from teardown operation."""

    success: bool
    deleted_resources: list[str] = Field(
        default_factory=list,
        description="List of resources that were deleted",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="List of errors encountered during teardown",
    )
    message: str | None = None
