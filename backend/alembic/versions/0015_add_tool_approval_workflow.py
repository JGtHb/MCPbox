"""Add tool approval workflow fields.

Revision ID: 0015
Revises: 0014
Create Date: 2024-01-19

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create approval_status enum
    approval_status = sa.Enum(
        "draft",
        "pending_review",
        "approved",
        "rejected",
        name="approval_status",
        create_constraint=True,
    )
    approval_status.create(op.get_bind(), checkfirst=True)

    # Add approval columns to tools table
    op.add_column(
        "tools",
        sa.Column(
            "approval_status",
            approval_status,
            nullable=False,
            server_default="draft",
        ),
    )
    op.add_column(
        "tools",
        sa.Column("approval_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tools",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tools",
        sa.Column("approved_by", sa.String(255), nullable=True),
    )
    op.add_column(
        "tools",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "tools",
        sa.Column("created_by", sa.String(255), nullable=True),
    )
    op.add_column(
        "tools",
        sa.Column("publish_notes", sa.Text(), nullable=True),
    )

    # Add index for filtering by approval status
    op.create_index(
        "ix_tools_approval_status",
        "tools",
        ["approval_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_tools_approval_status", table_name="tools")
    op.drop_column("tools", "publish_notes")
    op.drop_column("tools", "created_by")
    op.drop_column("tools", "rejection_reason")
    op.drop_column("tools", "approved_by")
    op.drop_column("tools", "approved_at")
    op.drop_column("tools", "approval_requested_at")
    op.drop_column("tools", "approval_status")

    # Drop enum type
    sa.Enum(name="approval_status").drop(op.get_bind(), checkfirst=True)
