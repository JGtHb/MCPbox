"""Pydantic schemas for authentication API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuthStatusResponse(BaseModel):
    """Response for auth status check."""

    setup_required: bool = Field(description="True if no admin user exists and setup is needed")
    onboarding_completed: bool = Field(
        default=True,
        description="True if the onboarding wizard has been completed (or dismissed)",
    )


class SetupRequest(BaseModel):
    """Request for initial admin setup."""

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$",
        description="Username (3-50 chars, alphanumeric and underscore, must start with letter)",
    )
    password: str = Field(
        ...,
        min_length=12,
        max_length=128,
        description="Password (minimum 12 characters)",
    )


class SetupResponse(BaseModel):
    """Response after successful setup."""

    message: str
    username: str


class LoginRequest(BaseModel):
    """Request for login."""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """Response with JWT tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token expiry in seconds")


class RefreshRequest(BaseModel):
    """Request for token refresh."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Request for logout with optional refresh token revocation (SEC-023)."""

    refresh_token: str | None = Field(
        None,
        description="Refresh token to revoke. If provided, the refresh token is blacklisted to prevent reuse.",
    )


class ChangePasswordRequest(BaseModel):
    """Request for password change."""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(
        ...,
        min_length=12,
        max_length=128,
        description="New password (minimum 12 characters)",
    )


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


class UserResponse(BaseModel):
    """Response with user information."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
