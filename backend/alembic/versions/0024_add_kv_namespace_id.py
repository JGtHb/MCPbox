"""Add kv_namespace_id to cloudflare_configs for OAuth KV namespace.

Stores the Cloudflare KV namespace ID used by the Worker's OAuth provider
for token and grant storage.

Revision ID: 0024
Revises: 0023
Create Date: 2026-02-08

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cloudflare_configs",
        sa.Column("kv_namespace_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cloudflare_configs", "kv_namespace_id")
