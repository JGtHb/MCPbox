"""Pydantic schemas for Credential API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

AuthType = Literal[
    "none",
    "api_key_header",
    "api_key_query",
    "bearer",
    "basic",
    "oauth2",
    "custom_header",
]

OAuthGrantType = Literal["client_credentials", "authorization_code"]


class CredentialCreate(BaseModel):
    """Schema for creating a new credential."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=500)
    auth_type: AuthType

    # For api_key_header, api_key_query, bearer, custom_header
    header_name: str | None = Field(None, max_length=255)
    query_param_name: str | None = Field(None, max_length=255)
    value: str | None = Field(None, description="The secret value (will be encrypted)")

    # For basic auth
    username: str | None = None
    password: str | None = None

    # For OAuth 2.0
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_token_url: str | None = None
    oauth_scopes: list[str] | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    # OAuth 2.0 Authorization Code Flow
    oauth_grant_type: OAuthGrantType | None = "client_credentials"
    oauth_authorization_url: str | None = None

    @model_validator(mode="after")
    def validate_auth_fields(self) -> "CredentialCreate":
        """Validate that required fields are present for each auth type."""
        if self.auth_type == "api_key_header":
            if not self.header_name or not self.value:
                raise ValueError("api_key_header requires header_name and value")
        elif self.auth_type == "api_key_query":
            if not self.query_param_name or not self.value:
                raise ValueError("api_key_query requires query_param_name and value")
        elif self.auth_type == "bearer":
            if not self.value:
                raise ValueError("bearer requires value (the token)")
        elif self.auth_type == "basic":
            if not self.username or not self.password:
                raise ValueError("basic requires username and password")
        elif self.auth_type == "oauth2":
            if not self.oauth_client_id or not self.oauth_token_url:
                raise ValueError("oauth2 requires oauth_client_id and oauth_token_url")
            # Authorization code flow also requires authorization URL
            if self.oauth_grant_type == "authorization_code":
                if not self.oauth_authorization_url:
                    raise ValueError(
                        "oauth2 with authorization_code grant requires oauth_authorization_url"
                    )
        elif self.auth_type == "custom_header":
            if not self.header_name or not self.value:
                raise ValueError("custom_header requires header_name and value")
        return self


class CredentialUpdate(BaseModel):
    """Schema for updating a credential."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=500)

    # Allow updating the value
    value: str | None = None
    username: str | None = None
    password: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None


TokenStatus = Literal["valid", "expiring_soon", "expired", "not_configured"]


class CredentialResponse(BaseModel):
    """Schema for credential response.

    NOTE: Secret values are NEVER returned in responses.
    We use has_* fields to indicate if values are configured.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    server_id: UUID
    name: str
    description: str | None
    auth_type: str
    header_name: str | None
    query_param_name: str | None
    oauth_client_id: str | None
    oauth_token_url: str | None
    oauth_scopes: list[str] | None
    access_token_expires_at: datetime | None = None
    # OAuth 2.0 Authorization Code Flow fields
    oauth_grant_type: str | None = None
    oauth_authorization_url: str | None = None
    # OAuth flow status (set during flow, cleared after)
    oauth_flow_pending: bool = False
    # Indicators for configured values (actual values are never returned)
    has_value: bool = False
    has_username: bool = False
    has_password: bool = False
    has_access_token: bool = False
    has_refresh_token: bool = False
    # Token status for OAuth credentials
    token_status: TokenStatus | None = None
    token_expires_in_seconds: int | None = None
    created_at: datetime
    updated_at: datetime


class CredentialListResponse(BaseModel):
    """Schema for credential list response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    auth_type: str
    description: str | None


class CredentialListPaginatedResponse(BaseModel):
    """Schema for paginated credential list response."""

    items: list[CredentialListResponse]
    total: int
    page: int
    page_size: int
    pages: int


class CredentialForInjection(BaseModel):
    """Schema for credential data needed for container injection.

    This is internal only - never exposed via API.
    """

    name: str
    auth_type: str
    header_name: str | None
    query_param_name: str | None
    value: str | None  # Decrypted
    username: str | None  # Decrypted
    password: str | None  # Decrypted
    access_token: str | None  # Decrypted


# OAuth Flow Schemas
class OAuthStartResponse(BaseModel):
    """Response when starting OAuth authorization code flow."""

    authorization_url: str = Field(..., description="URL to redirect user to for authorization")
    state: str = Field(..., description="CSRF state parameter")
    credential_id: UUID = Field(..., description="ID of the credential being authorized")


class OAuthCallbackRequest(BaseModel):
    """Request for OAuth callback handling."""

    code: str = Field(..., description="Authorization code from OAuth provider")
    state: str = Field(..., description="State parameter for CSRF validation")


class OAuthCallbackResponse(BaseModel):
    """Response after successful OAuth callback."""

    success: bool = True
    credential_id: UUID
    message: str = "OAuth authorization successful"
    has_access_token: bool = True
    has_refresh_token: bool = False
    access_token_expires_at: datetime | None = None


class OAuthRefreshResponse(BaseModel):
    """Response after token refresh."""

    success: bool = True
    credential_id: UUID
    message: str = "Token refreshed successfully"
    access_token_expires_at: datetime | None = None


class OAuthProvider(BaseModel):
    """OAuth provider preset configuration."""

    id: str = Field(..., description="Provider identifier (e.g., 'google', 'github')")
    name: str = Field(..., description="Display name")
    authorization_url: str = Field(..., description="Authorization endpoint URL")
    token_url: str = Field(..., description="Token endpoint URL")
    scopes: list[str] = Field(default_factory=list, description="Common scopes")
    docs_url: str | None = Field(None, description="Link to OAuth documentation")
