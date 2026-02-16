"""ServerSecret model - stores encrypted secrets for MCP servers."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.server import Server


class ServerSecret(BaseModel):
    """Encrypted key-value secret for an MCP server.

    Secrets are per-server (shared by all tools in that server).
    Values are encrypted with AES-256-GCM at rest.

    LLMs can create empty placeholders (key + description, no value).
    Admins set actual values via the UI. Secrets never pass through the LLM.

    Tool code accesses secrets via: secrets["KEY_NAME"]
    """

    __tablename__ = "server_secrets"

    __table_args__ = (
        UniqueConstraint("server_id", "key_name", name="uq_server_secrets_server_key"),
    )

    # Parent server
    server_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Secret key name (e.g., "THEIRSTACK_API_KEY")
    key_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Encrypted value (NULL means placeholder not yet filled by admin)
    encrypted_value: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)

    # Human-readable description of what this secret is for
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationship
    server: Mapped["Server"] = relationship("Server", back_populates="secrets")

    @property
    def has_value(self) -> bool:
        """Whether the secret has a value set."""
        return self.encrypted_value is not None

    def __repr__(self) -> str:
        return f"<ServerSecret {self.key_name} (server_id={self.server_id}, has_value={self.has_value})>"
