"""Add cloudflare_configs table for remote access setup wizard.

Revision ID: 0021
Revises: 0020
Create Date: 2026-01-31

Stores Cloudflare API token, tunnel, VPC service, Worker, and MCP Portal
configuration for the automated remote access setup wizard.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloudflare_configs",
        sa.Column("id", sa.UUID(), nullable=False),
        # Encrypted API token
        sa.Column("encrypted_api_token", sa.Text(), nullable=False),
        # Account info
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        # Zero Trust info
        sa.Column("team_domain", sa.String(length=255), nullable=True),
        # Tunnel info
        sa.Column("tunnel_id", sa.String(length=64), nullable=True),
        sa.Column("tunnel_name", sa.String(length=255), nullable=True),
        sa.Column("encrypted_tunnel_token", sa.Text(), nullable=True),
        # VPC Service info
        sa.Column("vpc_service_id", sa.String(length=64), nullable=True),
        sa.Column("vpc_service_name", sa.String(length=255), nullable=True),
        # Worker info
        sa.Column("worker_name", sa.String(length=255), nullable=True),
        sa.Column("worker_url", sa.String(length=1024), nullable=True),
        sa.Column("encrypted_service_token", sa.Text(), nullable=True),
        # MCP Server info
        sa.Column("mcp_server_id", sa.String(length=255), nullable=True),
        # MCP Portal info
        sa.Column("mcp_portal_id", sa.String(length=255), nullable=True),
        sa.Column("mcp_portal_hostname", sa.String(length=255), nullable=True),
        sa.Column("mcp_portal_aud", sa.String(length=128), nullable=True),
        # Wizard step tracking
        sa.Column("completed_step", sa.Integer(), nullable=False, server_default="0"),
        # Status
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Timestamps
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

    # Index on account_id for lookups
    op.create_index(
        "ix_cloudflare_configs_account_id",
        "cloudflare_configs",
        ["account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cloudflare_configs_account_id", table_name="cloudflare_configs")
    op.drop_table("cloudflare_configs")
