"""Add server_secrets table and drop legacy credentials table.

Revision ID: 0029
Revises: 0028
Create Date: 2026-02-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create new server_secrets table
    op.create_table(
        "server_secrets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key_name", sa.String(255), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
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
            ["server_id"],
            ["servers.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "key_name", name="uq_server_secrets_server_key"),
    )
    op.create_index(
        "ix_server_secrets_server_id",
        "server_secrets",
        ["server_id"],
    )

    # Drop legacy credentials table (replaced by server_secrets)
    op.drop_table("credentials")


def downgrade() -> None:
    # Recreate legacy credentials table
    op.create_table(
        "credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("auth_type", sa.String(50), nullable=False),
        sa.Column("header_name", sa.String(255), nullable=True),
        sa.Column("query_param_name", sa.String(255), nullable=True),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=True),
        sa.Column("username", sa.LargeBinary(), nullable=True),
        sa.Column("password", sa.LargeBinary(), nullable=True),
        sa.Column("access_token", sa.LargeBinary(), nullable=True),
        sa.Column("refresh_token", sa.LargeBinary(), nullable=True),
        sa.Column("token_url", sa.String(1024), nullable=True),
        sa.Column("client_id", sa.LargeBinary(), nullable=True),
        sa.Column("client_secret", sa.LargeBinary(), nullable=True),
        sa.Column("scope", sa.String(1024), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
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
            ["server_id"],
            ["servers.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.drop_index("ix_server_secrets_server_id", table_name="server_secrets")
    op.drop_table("server_secrets")
