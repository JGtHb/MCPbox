"""Add MCP passthrough support.

Creates external_mcp_sources table and adds tool_type, external_source_id,
and external_tool_name columns to tools table.

Revision ID: 0031
Revises: 0030
Create Date: 2026-02-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum types using raw SQL with IF NOT EXISTS to avoid conflicts
    op.execute("CREATE TYPE tool_type AS ENUM ('python_code', 'mcp_passthrough')")
    op.execute("CREATE TYPE external_mcp_auth_type AS ENUM ('none', 'bearer', 'header')")
    op.execute("CREATE TYPE external_mcp_transport_type AS ENUM ('streamable_http', 'sse')")
    op.execute("CREATE TYPE external_mcp_source_status AS ENUM ('active', 'error', 'disabled')")

    # Create external_mcp_sources table using raw SQL column types to avoid
    # SQLAlchemy's automatic enum creation in before_create events
    op.create_table(
        "external_mcp_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "auth_type",
            postgresql.ENUM("none", "bearer", "header", name="external_mcp_auth_type", create_type=False),
            nullable=False,
            server_default="none",
        ),
        sa.Column("auth_secret_name", sa.String(255), nullable=True),
        sa.Column("auth_header_name", sa.String(255), nullable=True),
        sa.Column(
            "transport_type",
            postgresql.ENUM("streamable_http", "sse", name="external_mcp_transport_type", create_type=False),
            nullable=False,
            server_default="streamable_http",
        ),
        sa.Column(
            "status",
            postgresql.ENUM("active", "error", "disabled", name="external_mcp_source_status", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tool_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
            ["server_id"],
            ["servers.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add new columns to tools table
    op.add_column(
        "tools",
        sa.Column(
            "tool_type",
            postgresql.ENUM("python_code", "mcp_passthrough", name="tool_type", create_type=False),
            nullable=False,
            server_default="python_code",
        ),
    )
    op.add_column(
        "tools",
        sa.Column(
            "external_source_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tools",
        sa.Column("external_tool_name", sa.String(255), nullable=True),
    )
    op.create_foreign_key(
        "fk_tools_external_source_id",
        "tools",
        "external_mcp_sources",
        ["external_source_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tools_external_source_id", "tools", type_="foreignkey")
    op.drop_column("tools", "external_tool_name")
    op.drop_column("tools", "external_source_id")
    op.drop_column("tools", "tool_type")
    op.drop_table("external_mcp_sources")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS external_mcp_source_status")
    op.execute("DROP TYPE IF EXISTS external_mcp_transport_type")
    op.execute("DROP TYPE IF EXISTS external_mcp_auth_type")
    op.execute("DROP TYPE IF EXISTS tool_type")
