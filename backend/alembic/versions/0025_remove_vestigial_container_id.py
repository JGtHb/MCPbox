"""Remove vestigial container_id column from servers table.

This column was part of the original per-server container architecture
and has never been read or written since the switch to a shared sandbox.

Revision ID: 0025
Revises: 0024
Create Date: 2026-02-12

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("servers", "container_id")


def downgrade() -> None:
    op.add_column(
        "servers",
        sa.Column("container_id", sa.String(length=64), nullable=True),
    )
