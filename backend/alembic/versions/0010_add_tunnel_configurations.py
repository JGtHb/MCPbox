"""Add tunnel_configurations table for named tunnel management.

This migration creates a table to store multiple named tunnel profiles,
allowing users to save and switch between different Cloudflare tunnel
configurations with custom subdomains.

Revision ID: 0010
Revises: 0009
Create Date: 2026-01-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tunnel_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tunnel_token", sa.Text(), nullable=True),
        sa.Column("public_url", sa.String(length=1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=False),
        sa.Column("gateway_token", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create index for quick lookup of active configuration
    op.create_index(
        "ix_tunnel_configurations_is_active",
        "tunnel_configurations",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tunnel_configurations_is_active", table_name="tunnel_configurations")
    op.drop_table("tunnel_configurations")
