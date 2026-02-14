"""Add performance indexes.

Revision ID: 0011
Revises: 0010
Create Date: 2026-01-16

Adds indexes for frequently queried columns to improve performance.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add index on tools.server_id for faster lookups when listing tools by server
    # This is a frequently used query pattern (list tools for a server)
    # if_not_exists: ForeignKey columns may already have auto-generated indexes
    op.create_index(
        "ix_tools_server_id",
        "tools",
        ["server_id"],
        if_not_exists=True,
    )

    # Add index on credentials.server_id for faster lookups
    op.create_index(
        "ix_credentials_server_id",
        "credentials",
        ["server_id"],
        if_not_exists=True,
    )

    # Add index on tool_versions.tool_id for version history queries
    op.create_index(
        "ix_tool_versions_tool_id",
        "tool_versions",
        ["tool_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_tool_versions_tool_id", table_name="tool_versions")
    op.drop_index("ix_credentials_server_id", table_name="credentials")
    op.drop_index("ix_tools_server_id", table_name="tools")
