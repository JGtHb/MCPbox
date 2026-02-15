"""CloudflareConfig model - stores Cloudflare remote access wizard state and configuration."""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class CloudflareConfig(BaseModel):
    """Cloudflare Configuration model.

    Stores the state and configuration for the Cloudflare remote access setup wizard.
    Only one active configuration is supported at a time.
    """

    __tablename__ = "cloudflare_configs"

    # Encrypted API token (using MCPBOX_ENCRYPTION_KEY)
    encrypted_api_token: Mapped[str] = mapped_column(Text, nullable=False)

    # Account info from token verification
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Zero Trust organization info (for OIDC endpoint URLs)
    team_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Tunnel info
    tunnel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tunnel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Tunnel connector token (encrypted) - for display/copy in UI
    encrypted_tunnel_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    # VPC Service info
    vpc_service_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vpc_service_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Worker info
    worker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    worker_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Service token for MCPbox authentication (encrypted)
    encrypted_service_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    # KV namespace ID for OAuth token storage
    kv_namespace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # SaaS OIDC Access Application ID (for Access for SaaS)
    access_app_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # OIDC client credentials from the SaaS OIDC application (encrypted)
    encrypted_access_client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_access_client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cookie encryption key for Worker approval cookies (encrypted, generated once)
    encrypted_cookie_encryption_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Access policy configuration (enforced at the OIDC layer by Cloudflare Access)
    access_policy_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    access_policy_emails: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_policy_email_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Wizard step tracking (0-5, where 5 is complete)
    completed_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Status: pending, active, error
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<CloudflareConfig account={self.account_id} step={self.completed_step} status={self.status}>"
