"""Add token_blacklist table for persistent JWT revocation.

Moves the in-memory JTI blacklist to a database table so that
revoked tokens remain invalid across process restarts (SEC-009).

Revision ID: 0036
Revises: 0035
Create Date: 2026-02-18

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "token_blacklist",
        sa.Column("jti", sa.String(64), primary_key=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("token_blacklist")
