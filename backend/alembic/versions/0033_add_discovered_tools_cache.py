"""Add discovered tools cache to external MCP sources.

Caches the discovered tool list as JSONB so admins can browse and import
tools without re-discovering from the live MCP server each time.

Revision ID: 0033
Revises: 0032
Create Date: 2026-02-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "external_mcp_sources",
        sa.Column("discovered_tools_cache", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("external_mcp_sources", "discovered_tools_cache")
