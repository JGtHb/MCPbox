"""Add activity_logs table for observability.

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create log_type enum
    log_type_enum = postgresql.ENUM(
        "mcp_request",
        "mcp_response",
        "network",
        "alert",
        "error",
        "system",
        name="log_type",
        create_type=False,
    )
    log_type_enum.create(op.get_bind(), checkfirst=True)

    # Create log_level enum
    log_level_enum = postgresql.ENUM(
        "debug",
        "info",
        "warning",
        "error",
        name="log_level",
        create_type=False,
    )
    log_level_enum.create(op.get_bind(), checkfirst=True)

    # Create activity_logs table
    op.create_table(
        "activity_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "server_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("servers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("log_type", log_type_enum, nullable=False),
        sa.Column("level", log_level_enum, nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # Create indexes
    op.create_index("ix_activity_logs_server_id", "activity_logs", ["server_id"])
    op.create_index("ix_activity_logs_log_type", "activity_logs", ["log_type"])
    op.create_index("ix_activity_logs_request_id", "activity_logs", ["request_id"])
    op.create_index(
        "ix_activity_logs_server_created",
        "activity_logs",
        ["server_id", "created_at"],
    )
    op.create_index(
        "ix_activity_logs_type_created",
        "activity_logs",
        ["log_type", "created_at"],
    )
    op.create_index(
        "ix_activity_logs_level_created",
        "activity_logs",
        ["level", "created_at"],
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_activity_logs_level_created", table_name="activity_logs")
    op.drop_index("ix_activity_logs_type_created", table_name="activity_logs")
    op.drop_index("ix_activity_logs_server_created", table_name="activity_logs")
    op.drop_index("ix_activity_logs_request_id", table_name="activity_logs")
    op.drop_index("ix_activity_logs_log_type", table_name="activity_logs")
    op.drop_index("ix_activity_logs_server_id", table_name="activity_logs")

    # Drop table
    op.drop_table("activity_logs")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS log_level")
    op.execute("DROP TYPE IF EXISTS log_type")
