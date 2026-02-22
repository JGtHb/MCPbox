"""Add allowed_cors_origins and allowed_redirect_uris to cloudflare_configs.

Admin-configurable origins for Worker CORS and OAuth redirect URI validation.
These supplement the hardcoded defaults (claude.ai, localhost, etc.).

Revision ID: 0038
Revises: 0037
Create Date: 2026-02-22

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cloudflare_configs",
        sa.Column("allowed_cors_origins", sa.Text(), nullable=True),
    )
    op.add_column(
        "cloudflare_configs",
        sa.Column("allowed_redirect_uris", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cloudflare_configs", "allowed_redirect_uris")
    op.drop_column("cloudflare_configs", "allowed_cors_origins")
