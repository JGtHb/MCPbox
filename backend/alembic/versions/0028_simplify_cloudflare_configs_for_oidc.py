"""Simplify cloudflare_configs for OIDC direct Worker connection.

Drop unused MCP Server/Portal columns (MCP clients now connect directly
to the Worker URL) and add cookie encryption key for stable approval
cookie management.

Revision ID: 0028
Revises: 0027
Create Date: 2026-02-15

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add stable cookie encryption key column
    op.add_column(
        "cloudflare_configs",
        sa.Column("encrypted_cookie_encryption_key", sa.Text(), nullable=True),
    )

    # Drop unused MCP Server/Portal columns
    op.drop_column("cloudflare_configs", "mcp_server_id")
    op.drop_column("cloudflare_configs", "mcp_portal_id")
    op.drop_column("cloudflare_configs", "mcp_portal_hostname")
    op.drop_column("cloudflare_configs", "mcp_portal_aud")


def downgrade() -> None:
    # Re-add MCP Server/Portal columns
    op.add_column(
        "cloudflare_configs",
        sa.Column("mcp_portal_aud", sa.String(128), nullable=True),
    )
    op.add_column(
        "cloudflare_configs",
        sa.Column("mcp_portal_hostname", sa.String(255), nullable=True),
    )
    op.add_column(
        "cloudflare_configs",
        sa.Column("mcp_portal_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "cloudflare_configs",
        sa.Column("mcp_server_id", sa.String(255), nullable=True),
    )

    # Drop cookie encryption key column
    op.drop_column("cloudflare_configs", "encrypted_cookie_encryption_key")
