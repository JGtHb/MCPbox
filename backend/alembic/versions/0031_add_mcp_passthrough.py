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
    # Create enum types
    tool_type_enum = sa.Enum("python_code", "mcp_passthrough", name="tool_type")
    tool_type_enum.create(op.get_bind(), checkfirst=True)

    external_mcp_auth_type_enum = sa.Enum("none", "bearer", "header", name="external_mcp_auth_type")
    external_mcp_auth_type_enum.create(op.get_bind(), checkfirst=True)

    external_mcp_transport_type_enum = sa.Enum(
        "streamable_http", "sse", name="external_mcp_transport_type"
    )
    external_mcp_transport_type_enum.create(op.get_bind(), checkfirst=True)

    external_mcp_source_status_enum = sa.Enum(
        "active", "error", "disabled", name="external_mcp_source_status"
    )
    external_mcp_source_status_enum.create(op.get_bind(), checkfirst=True)

    # Create external_mcp_sources table
    op.create_table(
        "external_mcp_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "auth_type",
            external_mcp_auth_type_enum,
            nullable=False,
            server_default="none",
        ),
        sa.Column("auth_secret_name", sa.String(255), nullable=True),
        sa.Column("auth_header_name", sa.String(255), nullable=True),
        sa.Column(
            "transport_type",
            external_mcp_transport_type_enum,
            nullable=False,
            server_default="streamable_http",
        ),
        sa.Column(
            "status",
            external_mcp_source_status_enum,
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
            tool_type_enum,
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
    sa.Enum(name="external_mcp_source_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="external_mcp_transport_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="external_mcp_auth_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tool_type").drop(op.get_bind(), checkfirst=True)
