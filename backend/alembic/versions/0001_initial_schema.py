"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-02-27

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Standalone tables (no foreign keys) ---

    op.create_table(
        "admin_users",
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("password_version", sa.Integer(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_users_username"), "admin_users", ["username"], unique=True
    )

    op.create_table(
        "cloudflare_configs",
        sa.Column("encrypted_api_token", sa.Text(), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("team_domain", sa.String(length=255), nullable=True),
        sa.Column("tunnel_id", sa.String(length=64), nullable=True),
        sa.Column("tunnel_name", sa.String(length=255), nullable=True),
        sa.Column("encrypted_tunnel_token", sa.Text(), nullable=True),
        sa.Column("vpc_service_id", sa.String(length=64), nullable=True),
        sa.Column("vpc_service_name", sa.String(length=255), nullable=True),
        sa.Column("worker_name", sa.String(length=255), nullable=True),
        sa.Column("worker_url", sa.String(length=1024), nullable=True),
        sa.Column("encrypted_service_token", sa.Text(), nullable=True),
        sa.Column("kv_namespace_id", sa.String(length=64), nullable=True),
        sa.Column("access_app_id", sa.String(length=64), nullable=True),
        sa.Column("encrypted_access_client_id", sa.Text(), nullable=True),
        sa.Column("encrypted_access_client_secret", sa.Text(), nullable=True),
        sa.Column("encrypted_cookie_encryption_key", sa.Text(), nullable=True),
        sa.Column("access_policy_type", sa.String(length=16), nullable=True),
        sa.Column("access_policy_emails", sa.Text(), nullable=True),
        sa.Column("access_policy_email_domain", sa.String(length=255), nullable=True),
        sa.Column("allowed_cors_origins", sa.Text(), nullable=True),
        sa.Column("allowed_redirect_uris", sa.Text(), nullable=True),
        sa.Column("completed_step", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "global_config",
        sa.Column("config_key", sa.String(length=50), nullable=False),
        sa.Column(
            "allowed_modules",
            postgresql.ARRAY(sa.String(length=255)),
            nullable=True,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("config_key"),
    )

    op.create_table(
        "servers",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "imported",
                "ready",
                "running",
                "stopped",
                "error",
                name="server_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "allowed_hosts",
            postgresql.ARRAY(sa.String(length=255)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("default_timeout_ms", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=255), nullable=False, comment="Setting key (unique identifier)"),
        sa.Column("value", sa.Text(), nullable=True, comment="Setting value (may be encrypted for sensitive data)"),
        sa.Column("encrypted", sa.Boolean(), nullable=False, comment="Whether the value is encrypted"),
        sa.Column("description", sa.String(length=500), nullable=True, comment="Human-readable description of this setting"),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_settings_key"), "settings", ["key"], unique=True)

    op.create_table(
        "token_blacklist",
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index(
        op.f("ix_token_blacklist_expires_at"),
        "token_blacklist",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "tunnel_configurations",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tunnel_token", sa.Text(), nullable=True),
        sa.Column("public_url", sa.String(length=1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- Tables with FK to servers ---

    op.create_table(
        "activity_logs",
        sa.Column("server_id", sa.UUID(), nullable=True),
        sa.Column(
            "log_type",
            sa.Enum(
                "mcp_request",
                "mcp_response",
                "network",
                "alert",
                "error",
                "system",
                "audit",
                name="log_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "level",
            sa.Enum("debug", "info", "warning", "error", name="log_level"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_activity_logs_level_created",
        "activity_logs",
        ["level", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_activity_logs_log_type"), "activity_logs", ["log_type"], unique=False
    )
    op.create_index(
        op.f("ix_activity_logs_request_id"),
        "activity_logs",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        "ix_activity_logs_server_created",
        "activity_logs",
        ["server_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_activity_logs_server_id"), "activity_logs", ["server_id"], unique=False
    )
    op.create_index(
        "ix_activity_logs_type_created",
        "activity_logs",
        ["log_type", "created_at"],
        unique=False,
    )

    op.create_table(
        "external_mcp_sources",
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "auth_type",
            sa.Enum(
                "none",
                "bearer",
                "header",
                "oauth",
                name="external_mcp_auth_type",
            ),
            nullable=False,
        ),
        sa.Column("auth_secret_name", sa.String(length=255), nullable=True),
        sa.Column("auth_header_name", sa.String(length=255), nullable=True),
        sa.Column(
            "transport_type",
            sa.Enum(
                "streamable_http", "sse", name="external_mcp_transport_type"
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("active", "error", "disabled", name="external_mcp_source_status"),
            nullable=False,
        ),
        sa.Column("oauth_tokens_encrypted", sa.Text(), nullable=True),
        sa.Column("oauth_issuer", sa.String(length=2000), nullable=True),
        sa.Column("oauth_client_id", sa.String(length=255), nullable=True),
        sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tool_count", sa.Integer(), nullable=False),
        sa.Column(
            "discovered_tools_cache",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "server_secrets",
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("key_name", sa.String(length=255), nullable=False),
        sa.Column("encrypted_value", postgresql.BYTEA(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "key_name", name="uq_server_secrets_server_key"),
    )

    # --- Tables with FK to servers + external_mcp_sources ---

    op.create_table(
        "tools",
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "input_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=True),
        sa.Column(
            "tool_type",
            sa.Enum("python_code", "mcp_passthrough", name="tool_type"),
            server_default="python_code",
            nullable=False,
        ),
        sa.Column("python_code", sa.Text(), nullable=True),
        sa.Column("external_source_id", sa.UUID(), nullable=True),
        sa.Column("external_tool_name", sa.String(length=255), nullable=True),
        sa.Column(
            "code_dependencies",
            postgresql.ARRAY(sa.String(length=255)),
            nullable=True,
        ),
        sa.Column("current_version", sa.Integer(), nullable=False, comment="Current version number of this tool"),
        sa.Column(
            "approval_status",
            sa.Enum(
                "draft", "pending_review", "approved", "rejected", name="approval_status"
            ),
            nullable=False,
        ),
        sa.Column("approval_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("publish_notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["external_source_id"],
            ["external_mcp_sources.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "name", name="uq_tools_server_id_name"),
    )

    # --- Tables with FK to tools ---

    op.create_table(
        "module_requests",
        sa.Column("tool_id", sa.UUID(), nullable=False),
        sa.Column("module_name", sa.String(length=255), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="request_status"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_module_requests_pending_unique",
        "module_requests",
        ["tool_id", "module_name"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "network_access_requests",
        sa.Column("tool_id", sa.UUID(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="request_status"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Use COALESCE(port, 0) so NULL ports are treated as equal for uniqueness.
    # SQLAlchemy Index() can't express COALESCE, so we use raw SQL.
    op.execute(
        """
        CREATE UNIQUE INDEX ix_network_access_requests_pending_unique
        ON network_access_requests (tool_id, host, COALESCE(port, 0))
        WHERE status = 'pending'
        """
    )

    op.create_table(
        "tool_execution_logs",
        sa.Column("tool_id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column(
            "input_args", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "result", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("is_test", sa.Boolean(), nullable=False),
        sa.Column("executed_by", sa.String(length=255), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tool_execution_logs_server_created",
        "tool_execution_logs",
        ["server_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_tool_execution_logs_tool_created",
        "tool_execution_logs",
        ["tool_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "tool_versions",
        sa.Column("tool_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=True),
        sa.Column("python_code", sa.Text(), nullable=True),
        sa.Column(
            "input_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("change_summary", sa.String(length=500), nullable=True, comment="Brief description of what changed in this version"),
        sa.Column("change_source", sa.String(length=50), nullable=False, comment="Source of change: manual, llm, import, rollback"),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("tool_versions")
    op.drop_index(
        "ix_tool_execution_logs_tool_created", table_name="tool_execution_logs"
    )
    op.drop_index(
        "ix_tool_execution_logs_server_created", table_name="tool_execution_logs"
    )
    op.drop_table("tool_execution_logs")
    op.drop_index(
        "ix_network_access_requests_pending_unique",
        table_name="network_access_requests",
    )
    op.drop_table("network_access_requests")
    op.drop_index(
        "ix_module_requests_pending_unique", table_name="module_requests"
    )
    op.drop_table("module_requests")
    op.drop_table("tools")
    op.drop_table("server_secrets")
    op.drop_table("external_mcp_sources")
    op.drop_index("ix_activity_logs_type_created", table_name="activity_logs")
    op.drop_index(op.f("ix_activity_logs_server_id"), table_name="activity_logs")
    op.drop_index("ix_activity_logs_server_created", table_name="activity_logs")
    op.drop_index(op.f("ix_activity_logs_request_id"), table_name="activity_logs")
    op.drop_index(op.f("ix_activity_logs_log_type"), table_name="activity_logs")
    op.drop_index("ix_activity_logs_level_created", table_name="activity_logs")
    op.drop_table("activity_logs")
    op.drop_table("tunnel_configurations")
    op.drop_index(op.f("ix_token_blacklist_expires_at"), table_name="token_blacklist")
    op.drop_table("token_blacklist")
    op.drop_index(op.f("ix_settings_key"), table_name="settings")
    op.drop_table("settings")
    op.drop_table("servers")
    op.drop_table("global_config")
    op.drop_table("cloudflare_configs")
    op.drop_index(op.f("ix_admin_users_username"), table_name="admin_users")
    op.drop_table("admin_users")

    # Drop enum types
    for enum_name in [
        "approval_status",
        "external_mcp_auth_type",
        "external_mcp_source_status",
        "external_mcp_transport_type",
        "log_level",
        "log_type",
        "request_status",
        "server_status",
        "tool_type",
    ]:
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
