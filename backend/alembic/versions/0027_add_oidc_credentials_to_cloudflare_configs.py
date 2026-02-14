"""Add OIDC client credentials to cloudflare_configs.

Stores encrypted OIDC client_id and client_secret from the SaaS OIDC
application created in Cloudflare Access. These are used by the Worker
to authenticate users via OIDC (Access for SaaS).

Revision ID: 0027
Revises: 0026
Create Date: 2026-02-14

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cloudflare_configs",
        sa.Column("encrypted_access_client_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "cloudflare_configs",
        sa.Column("encrypted_access_client_secret", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cloudflare_configs", "encrypted_access_client_secret")
    op.drop_column("cloudflare_configs", "encrypted_access_client_id")
