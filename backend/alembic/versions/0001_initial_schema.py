"""Initial schema with servers, tools, and credentials.

Revision ID: 0001
Revises:
Create Date: 2026-01-11 19:15:02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create enum types
    source_type = postgresql.ENUM(
        "git", "upload", "api_builder", name="source_type", create_type=False
    )
    source_type.create(op.get_bind(), checkfirst=True)

    server_status = postgresql.ENUM(
        "imported",
        "building",
        "ready",
        "running",
        "stopped",
        "error",
        name="server_status",
        create_type=False,
    )
    server_status.create(op.get_bind(), checkfirst=True)

    network_mode = postgresql.ENUM(
        "isolated",
        "allowlist",
        "monitored",
        "learning",
        name="network_mode",
        create_type=False,
    )
    network_mode.create(op.get_bind(), checkfirst=True)

    auth_type = postgresql.ENUM(
        "none",
        "api_key_header",
        "api_key_query",
        "bearer",
        "basic",
        "oauth2",
        "custom_header",
        name="auth_type",
        create_type=False,
    )
    auth_type.create(op.get_bind(), checkfirst=True)

    # Create servers table
    op.create_table(
        "servers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "source_type",
            source_type,
            nullable=False,
            server_default="api_builder",
        ),
        sa.Column("repo_url", sa.String(length=1024), nullable=True),
        sa.Column("repo_branch", sa.String(length=255), nullable=False, server_default="main"),
        sa.Column("commit_hash", sa.String(length=40), nullable=True),
        sa.Column(
            "status",
            server_status,
            nullable=False,
            server_default="imported",
        ),
        sa.Column("container_id", sa.String(length=64), nullable=True),
        sa.Column(
            "network_mode",
            network_mode,
            nullable=False,
            server_default="isolated",
        ),
        sa.Column("allowed_hosts", postgresql.ARRAY(sa.String(length=255)), nullable=True),
        sa.Column("default_timeout_ms", sa.Integer(), nullable=False, server_default="30000"),
        sa.Column("generated_code", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_servers_name", "servers", ["name"])
    op.create_index("ix_servers_status", "servers", ["status"])

    # Create tools table
    op.create_table(
        "tools",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("timeout_ms", sa.Integer(), nullable=True),
        sa.Column("api_config", postgresql.JSONB(), nullable=True),
        sa.Column("input_schema", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "name", name="uq_tool_server_name"),
    )
    op.create_index("ix_tools_server_id", "tools", ["server_id"])

    # Create credentials table
    op.create_table(
        "credentials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "auth_type",
            auth_type,
            nullable=False,
            server_default="none",
        ),
        # Encrypted fields
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=True),
        sa.Column("encrypted_username", sa.LargeBinary(), nullable=True),
        sa.Column("encrypted_password", sa.LargeBinary(), nullable=True),
        sa.Column("encrypted_access_token", sa.LargeBinary(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.LargeBinary(), nullable=True),
        # Non-sensitive config
        sa.Column("header_name", sa.String(length=255), nullable=True),
        sa.Column("query_param_name", sa.String(length=255), nullable=True),
        sa.Column("oauth_client_id", sa.String(length=255), nullable=True),
        sa.Column("oauth_client_secret", sa.LargeBinary(), nullable=True),
        sa.Column("oauth_token_url", sa.String(length=1024), nullable=True),
        sa.Column("oauth_scopes", postgresql.ARRAY(sa.String(length=255)), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "name", name="uq_credential_server_name"),
    )
    op.create_index("ix_credentials_server_id", "credentials", ["server_id"])


def downgrade() -> None:
    op.drop_table("credentials")
    op.drop_table("tools")
    op.drop_table("servers")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS auth_type")
    op.execute("DROP TYPE IF EXISTS network_mode")
    op.execute("DROP TYPE IF EXISTS server_status")
    op.execute("DROP TYPE IF EXISTS source_type")
