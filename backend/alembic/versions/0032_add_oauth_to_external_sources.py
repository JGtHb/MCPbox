"""Add OAuth auth type and token storage to external MCP sources.

Adds 'oauth' to the external_mcp_auth_type enum and adds columns for
encrypted OAuth tokens, issuer URL, and client ID.

Revision ID: 0032
Revises: 0031
Create Date: 2026-02-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'oauth' to existing external_mcp_auth_type enum
    op.execute("ALTER TYPE external_mcp_auth_type ADD VALUE IF NOT EXISTS 'oauth'")

    # Add OAuth credential columns
    op.add_column(
        "external_mcp_sources",
        sa.Column("oauth_tokens_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "external_mcp_sources",
        sa.Column("oauth_issuer", sa.String(2000), nullable=True),
    )
    op.add_column(
        "external_mcp_sources",
        sa.Column("oauth_client_id", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("external_mcp_sources", "oauth_client_id")
    op.drop_column("external_mcp_sources", "oauth_issuer")
    op.drop_column("external_mcp_sources", "oauth_tokens_encrypted")
    # Note: PostgreSQL does not support removing enum values.
    # The 'oauth' value will remain in the enum type after downgrade.
