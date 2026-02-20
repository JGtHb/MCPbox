"""Add is_test column to tool_execution_logs.

Test code runs via mcpbox_test_code are now persisted alongside production
executions, distinguished by is_test=True so the UI can label them clearly.

Revision ID: 0037
Revises: 0036
Create Date: 2026-02-19

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool_execution_logs",
        sa.Column(
            "is_test",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("tool_execution_logs", "is_test")
