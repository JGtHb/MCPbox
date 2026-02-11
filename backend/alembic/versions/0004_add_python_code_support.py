"""Add Python code execution support for tools.

This migration adds:
- helper_code field to servers for shared Python code across actions
- execution_mode enum and field to tools (api_config vs python_code)
- python_code field to tools for custom Python implementations
- code_dependencies field to tools for pip package requirements

Revision ID: 0004
Revises: 0003
Create Date: 2026-01-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create execution_mode enum
    # - api_config: Tool uses api_config JSON to make HTTP calls (existing behavior)
    # - python_code: Tool uses custom Python code with main() entry point
    execution_mode_enum = postgresql.ENUM(
        "api_config",
        "python_code",
        name="execution_mode",
        create_type=False,
    )
    execution_mode_enum.create(op.get_bind(), checkfirst=True)

    # Add helper_code to servers table
    # This field stores shared Python code that can be imported by all actions
    # in this tool (e.g., pagination helpers, response parsers)
    op.add_column(
        "servers",
        sa.Column(
            "helper_code",
            sa.Text(),
            nullable=True,
            comment="Shared Python helper code for all actions in this tool",
        ),
    )

    # Add execution_mode to tools table
    # Defaults to 'api_config' for backward compatibility with existing tools
    op.add_column(
        "tools",
        sa.Column(
            "execution_mode",
            execution_mode_enum,
            nullable=False,
            server_default="api_config",
            comment="How this tool executes: api_config (HTTP) or python_code (custom)",
        ),
    )

    # Add python_code to tools table
    # Stores the Python code with main() function for python_code execution mode
    op.add_column(
        "tools",
        sa.Column(
            "python_code",
            sa.Text(),
            nullable=True,
            comment="Python code with async main() function for python_code mode",
        ),
    )

    # Add code_dependencies to tools table for pip packages
    op.add_column(
        "tools",
        sa.Column(
            "code_dependencies",
            ARRAY(sa.String(255)),
            nullable=True,
            comment="List of pip packages required by python_code",
        ),
    )

    # Add index on execution_mode for efficient filtering
    op.create_index(
        "ix_tools_execution_mode",
        "tools",
        ["execution_mode"],
    )


def downgrade() -> None:
    # Drop index
    op.drop_index("ix_tools_execution_mode", table_name="tools")

    # Drop columns
    op.drop_column("tools", "code_dependencies")
    op.drop_column("tools", "python_code")
    op.drop_column("tools", "execution_mode")
    op.drop_column("servers", "helper_code")

    # Drop enum
    op.execute("DROP TYPE IF EXISTS execution_mode")
