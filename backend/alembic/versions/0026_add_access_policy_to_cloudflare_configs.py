"""Add access policy fields to cloudflare_configs.

Stores the access policy configuration so it can be synced to both
Cloudflare Access policies and the Worker's ALLOWED_EMAILS secret.

Revision ID: 0026
Revises: 0025
Create Date: 2026-02-14

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cloudflare_configs",
        sa.Column("access_policy_type", sa.String(16), nullable=True),
    )
    op.add_column(
        "cloudflare_configs",
        sa.Column("access_policy_emails", sa.Text(), nullable=True),
    )
    op.add_column(
        "cloudflare_configs",
        sa.Column("access_policy_email_domain", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cloudflare_configs", "access_policy_email_domain")
    op.drop_column("cloudflare_configs", "access_policy_emails")
    op.drop_column("cloudflare_configs", "access_policy_type")
