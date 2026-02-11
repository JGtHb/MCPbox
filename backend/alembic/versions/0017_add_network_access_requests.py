"""Add network_access_requests table for LLM network whitelist requests.

Revision ID: 0017
Revises: 0016
Create Date: 2024-01-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Note: request_status enum already exists from migration 0016

    # Create network_access_requests table
    op.create_table(
        "network_access_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tool_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                name="request_status",
                create_constraint=False,
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
        "ix_network_access_requests_status",
        "network_access_requests",
        ["status"],
    )
    op.create_index(
        "ix_network_access_requests_tool_id",
        "network_access_requests",
        ["tool_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_network_access_requests_tool_id", table_name="network_access_requests"
    )
    op.drop_index(
        "ix_network_access_requests_status", table_name="network_access_requests"
    )
    op.drop_table("network_access_requests")
