"""Add access_app_id to cloudflare_configs table.

Revision ID: 0022
Revises: 0021
Create Date: 2026-02-01

Stores the Access Application ID created for JWT verification,
since MCP Portals created via API don't automatically create
an Access Application.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cloudflare_configs",
        sa.Column("access_app_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cloudflare_configs", "access_app_id")
