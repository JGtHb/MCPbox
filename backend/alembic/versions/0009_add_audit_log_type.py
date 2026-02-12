"""Add audit log type for security logging.

Revision ID: 0009
Revises: 0008
Create Date: 2024-01-15

"""

from alembic import op

# revision identifiers
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add 'audit' to log_type enum."""
    # Add new value to existing enum
    op.execute("ALTER TYPE log_type ADD VALUE IF NOT EXISTS 'audit'")


def downgrade() -> None:
    """Note: PostgreSQL doesn't support removing enum values.

    The 'audit' type will remain but won't be used after downgrade.
    """
    pass
