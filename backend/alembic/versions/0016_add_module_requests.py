"""Add module_requests table for LLM module whitelist requests.

Revision ID: 0016
Revises: 0015
Create Date: 2024-01-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create module_requests table
    # The request_status enum is created automatically by create_table
    op.create_table(
        "module_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tool_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("module_name", sa.String(255), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                name="request_status",
                create_constraint=True,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
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
            onupdate=sa.text("now()"),
            nullable=False,
        ),
    )

    # Add indexes
    op.create_index(
        "ix_module_requests_status",
        "module_requests",
        ["status"],
    )
    op.create_index(
        "ix_module_requests_tool_id",
        "module_requests",
        ["tool_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_module_requests_tool_id", table_name="module_requests")
    op.drop_index("ix_module_requests_status", table_name="module_requests")
    op.drop_table("module_requests")

    # Drop enum type
    sa.Enum(name="request_status").drop(op.get_bind(), checkfirst=True)
