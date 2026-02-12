"""Add tool version history for rollback support.

This migration adds:
- tool_versions table for storing snapshots of tool configurations
- current_version column on tools table to track version number

Revision ID: 0006
Revises: 0005
Create Date: 2026-01-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add current_version column to tools table
    op.add_column(
        "tools",
        sa.Column(
            "current_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Current version number of this tool",
        ),
    )

    # Create tool_versions table
    op.create_table(
        "tool_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tool_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_number",
            sa.Integer(),
            nullable=False,
        ),
        # Snapshot of tool state
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("timeout_ms", sa.Integer(), nullable=True),
        sa.Column("execution_mode", sa.String(20), nullable=False),
        sa.Column("api_config", postgresql.JSONB(), nullable=True),
        sa.Column("python_code", sa.Text(), nullable=True),
        sa.Column("input_schema", postgresql.JSONB(), nullable=True),
        # Metadata
        sa.Column(
            "change_summary",
            sa.String(500),
            nullable=True,
            comment="Brief description of what changed",
        ),
        sa.Column(
            "change_source",
            sa.String(50),
            nullable=False,
            server_default="manual",
            comment="Source: manual, llm, import, rollback",
        ),
        # Timestamps
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # Create indexes for efficient queries
    op.create_index(
        "ix_tool_versions_tool_id",
        "tool_versions",
        ["tool_id"],
    )
    op.create_index(
        "ix_tool_versions_tool_version",
        "tool_versions",
        ["tool_id", "version_number"],
        unique=True,
    )

    # Create initial version 1 entries for all existing tools
    op.execute(
        """
        INSERT INTO tool_versions (
            id, tool_id, version_number, name, description, enabled,
            timeout_ms, execution_mode, api_config, python_code, input_schema,
            change_summary, change_source, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            id,
            1,
            name,
            description,
            enabled,
            timeout_ms,
            execution_mode,
            api_config,
            python_code,
            input_schema,
            'Initial version',
            'migration',
            created_at,
            updated_at
        FROM tools
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tool_versions_tool_version", table_name="tool_versions")
    op.drop_index("ix_tool_versions_tool_id", table_name="tool_versions")
    op.drop_table("tool_versions")
    op.drop_column("tools", "current_version")
