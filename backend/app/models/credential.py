"""Credential model - stores encrypted credentials for MCP servers."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.server import Server


# Auth types per architecture doc
AuthType = Enum(
    "none",
    "api_key_header",
    "api_key_query",
    "bearer",
    "basic",
    "oauth2",
    "custom_header",
    name="auth_type",
    create_constraint=True,
)

# OAuth grant types
OAuthGrantType = Enum(
    "client_credentials",
    "authorization_code",
    name="oauth_grant_type",
    create_constraint=True,
)


class Credential(BaseModel):
    """Credential model for storing encrypted API credentials.

    All sensitive values are stored encrypted using AES-256-GCM.
    The encryption key is provided via environment variable.
    """

    __tablename__ = "credentials"

    # Parent server (1:1 relationship as per architecture - no sharing)
    server_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Credential metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Auth type determines which fields are used
    auth_type: Mapped[str] = mapped_column(AuthType, nullable=False)

    # For api_key_header, api_key_query, bearer, custom_header
    header_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    query_param_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_value: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)

    # For basic auth
    encrypted_username: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    encrypted_password: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)

    # For OAuth 2.0
    oauth_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oauth_client_secret: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    oauth_token_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    oauth_scopes: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text),
        nullable=True,
    )
    encrypted_access_token: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    encrypted_refresh_token: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # OAuth 2.0 Authorization Code Flow specific fields
    oauth_grant_type: Mapped[str | None] = mapped_column(
        OAuthGrantType,
        nullable=True,
        default="client_credentials",
    )
    oauth_authorization_url: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    # State for CSRF protection during OAuth flow (temporary, cleared after callback)
    oauth_state: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # PKCE code verifier (temporary, cleared after token exchange)
    oauth_code_verifier: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Relationship
    server: Mapped["Server"] = relationship("Server", back_populates="credentials")

    def __repr__(self) -> str:
        return f"<Credential {self.name} ({self.auth_type}) for server_id={self.server_id}>"
