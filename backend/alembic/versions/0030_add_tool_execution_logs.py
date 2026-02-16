"""Add tool_execution_logs table.

Revision ID: 0030
Revises: 0029
Create Date: 2026-02-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_execution_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("input_args", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("executed_by", sa.String(255), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["tool_id"],
            ["tools.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tool_execution_logs_tool_created",
        "tool_execution_logs",
        ["tool_id", "created_at"],
    )
    op.create_index(
        "ix_tool_execution_logs_server_created",
        "tool_execution_logs",
        ["server_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tool_execution_logs_server_created",
        table_name="tool_execution_logs",
    )
    op.drop_index(
        "ix_tool_execution_logs_tool_created",
        table_name="tool_execution_logs",
    )
    op.drop_table("tool_execution_logs")
