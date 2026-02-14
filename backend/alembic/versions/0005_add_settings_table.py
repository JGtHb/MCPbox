"""Add settings table for app configuration.

This migration adds:
- settings table for storing key-value configuration
- Used for LLM API keys, model preferences, feature toggles

Revision ID: 0005
Revises: 0004
Create Date: 2026-01-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create settings table
    op.create_table(
        "settings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "key",
            sa.String(255),
            nullable=False,
            unique=True,
            comment="Setting key (unique identifier)",
        ),
        sa.Column(
            "value",
            sa.Text(),
            nullable=True,
            comment="Setting value (may be encrypted for sensitive data)",
        ),
        sa.Column(
            "encrypted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether the value is encrypted",
        ),
        sa.Column(
            "description",
            sa.String(500),
            nullable=True,
            comment="Human-readable description of this setting",
        ),
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

    # Create index on key for fast lookups
    op.create_index("ix_settings_key", "settings", ["key"])

    # Insert default settings
    op.execute(
        """
        INSERT INTO settings (id, key, value, encrypted, description)
        VALUES
            (gen_random_uuid(), 'llm_enabled', 'false', false, 'Whether LLM features are enabled'),
            (gen_random_uuid(), 'llm_model', 'claude-sonnet-4-20250514', false, 'Default LLM model for code generation'),
            (gen_random_uuid(), 'anthropic_api_key', NULL, true, 'Anthropic API key for Claude')
        """
    )


def downgrade() -> None:
    op.drop_index("ix_settings_key", table_name="settings")
    op.drop_table("settings")
