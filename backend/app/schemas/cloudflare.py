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
    # SECURITY: tunnel_token removed from API response to prevent token leakage
    # via browser DevTools, HTTP proxy logs, or error tracking services.
    # The token is stored encrypted in the database and used automatically.
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
    # SECURITY: service_token removed from API response to prevent token leakage
    # via browser DevTools, HTTP proxy logs, or error tracking services.
    # The token is stored encrypted in the database and pushed to Worker by deploy script.
    message: str | None = None


# =============================================================================
# Step 5: Configure Access (OIDC)
# =============================================================================


class ConfigureJwtRequest(BaseModel):
    """Request to configure Worker OIDC authentication.

    Creates a SaaS OIDC Access Application (if not already created),
    sets up the Access Policy, and syncs OIDC secrets to the Worker.
    """

    config_id: UUID
    access_policy: AccessPolicyConfig | None = Field(
        default=None,
        description="Access policy configuration. Defaults to 'everyone' if not provided.",
    )


class ConfigureJwtResponse(BaseModel):
    """Response from Worker OIDC configuration."""

    success: bool
    team_domain: str
    worker_url: str = Field(
        default="",
        description="Worker URL — add this to your MCP client",
    )
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
    completed_step: int = Field(default=0, description="Last completed step (0-5)")
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

    # Access policy
    access_policy_type: str | None = None
    access_policy_emails: list[str] | None = None
    access_policy_email_domain: str | None = None

    # Admin-configurable allowed origins (additional to built-in defaults)
    allowed_cors_origins: list[str] | None = None
    allowed_redirect_uris: list[str] | None = None

    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UpdateAccessPolicyRequest(BaseModel):
    """Request to update the access policy on the Cloudflare Access SaaS application."""

    config_id: UUID
    access_policy: AccessPolicyConfig = Field(
        ...,
        description="New access policy configuration",
    )


class UpdateAccessPolicyResponse(BaseModel):
    """Response from updating access policy."""

    success: bool
    access_policy_synced: bool = Field(
        default=False,
        description="Whether the Cloudflare Access Policy was updated",
    )
    worker_synced: bool = Field(
        default=True,
        description="With Access for SaaS, policy is enforced at OIDC layer (no Worker sync needed)",
    )
    message: str | None = None


# =============================================================================
# Worker Configuration (CORS + Redirect URIs)
# =============================================================================


class UpdateWorkerConfigRequest(BaseModel):
    """Request to update Worker CORS origins and OAuth redirect URIs.

    These are *additional* origins/URIs beyond the built-in defaults
    (Claude, ChatGPT, OpenAI, Cloudflare, localhost).
    """

    config_id: UUID
    allowed_cors_origins: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Additional CORS origins to allow (e.g., 'https://my-mcp-client.example.com'). "
            "Built-in origins (Claude, ChatGPT, OpenAI, Cloudflare, localhost) are always included."
        ),
    )
    allowed_redirect_uris: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Additional OAuth redirect URI prefixes to allow "
            "(e.g., 'https://my-mcp-client.example.com/'). "
            "Built-in patterns (Claude, ChatGPT, OpenAI, Cloudflare, localhost) are always included."
        ),
    )

    @field_validator("allowed_cors_origins")
    @classmethod
    def validate_cors_origins(cls, v: list[str]) -> list[str]:
        validated = []
        for origin in v:
            origin = origin.strip().rstrip("/")
            if not origin:
                continue
            if not re.match(r"^https?://[a-zA-Z0-9]([a-zA-Z0-9._:-]*[a-zA-Z0-9])?$", origin):
                raise ValueError(
                    f"Invalid CORS origin: {origin!r}. "
                    "Must be a valid HTTP(S) origin (e.g., 'https://example.com')."
                )
            # Require HTTPS for non-localhost origins
            if origin.startswith("http://") and not re.match(
                r"^http://(localhost|127\.0\.0\.1)(:\d+)?$", origin
            ):
                raise ValueError(f"Non-localhost CORS origins must use HTTPS: {origin!r}")
            validated.append(origin)
        return validated

    @field_validator("allowed_redirect_uris")
    @classmethod
    def validate_redirect_uris(cls, v: list[str]) -> list[str]:
        validated = []
        for uri in v:
            uri = uri.strip()
            if not uri:
                continue
            if not re.match(r"^https?://[a-zA-Z0-9]", uri):
                raise ValueError(
                    f"Invalid redirect URI: {uri!r}. Must start with http:// or https://."
                )
            # Require HTTPS for non-localhost URIs
            if uri.startswith("http://") and not re.match(
                r"^http://(localhost|127\.0\.0\.1)(:\d+)?/", uri
            ):
                raise ValueError(f"Non-localhost redirect URIs must use HTTPS: {uri!r}")
            validated.append(uri)
        return validated


class UpdateWorkerConfigResponse(BaseModel):
    """Response from updating Worker configuration."""

    success: bool
    allowed_cors_origins: list[str] = Field(default_factory=list)
    allowed_redirect_uris: list[str] = Field(default_factory=list)
    kv_synced: bool = Field(
        default=False,
        description="Whether the config was synced to Worker KV",
    )
    message: str | None = None


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
