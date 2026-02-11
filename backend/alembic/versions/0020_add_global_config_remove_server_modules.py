"""Add global_config table and remove allowed_modules from servers.

Revision ID: 0020
Revises: 0019
Create Date: 2024-01-24

Module whitelist is now global instead of per-server.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create global_config table
    op.create_table(
        "global_config",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("config_key", sa.String(length=50), nullable=False),
        sa.Column(
            "allowed_modules",
            postgresql.ARRAY(sa.String(length=255)),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("config_key"),
    )

    # Remove allowed_modules from servers table
    op.drop_column("servers", "allowed_modules")


def downgrade() -> None:
    # Add allowed_modules back to servers
    op.add_column(
        "servers",
        sa.Column(
            "allowed_modules",
            postgresql.ARRAY(sa.String(length=255)),
            nullable=True,
        ),
    )

    # Drop global_config table
    op.drop_table("global_config")
