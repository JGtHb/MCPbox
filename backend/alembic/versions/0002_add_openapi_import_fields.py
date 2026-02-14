"""Add OpenAPI import fields to servers and tools.

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-11 19:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add OpenAPI import fields to servers
    op.add_column(
        "servers",
        sa.Column("openapi_spec", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "servers",
        sa.Column("import_source_url", sa.String(length=1024), nullable=True),
    )

    # Add source tracking fields to tools
    op.add_column(
        "tools",
        sa.Column("source_operation_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tools",
        sa.Column("source_path", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "tools",
        sa.Column("source_method", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    # Remove from tools
    op.drop_column("tools", "source_method")
    op.drop_column("tools", "source_path")
    op.drop_column("tools", "source_operation_id")

    # Remove from servers
    op.drop_column("servers", "import_source_url")
    op.drop_column("servers", "openapi_spec")
