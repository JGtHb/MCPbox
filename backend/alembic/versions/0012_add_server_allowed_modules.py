"""Add allowed_modules to servers table.

Revision ID: 0012
Revises: 0011
Create Date: 2025-01-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add allowed_modules column to servers table
    # NULL means use default modules, a list means custom modules
    op.add_column(
        "servers",
        sa.Column(
            "allowed_modules",
            postgresql.ARRAY(sa.String(255)),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("servers", "allowed_modules")
