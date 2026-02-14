"""Remove api_config execution mode and OpenAPI import support.

MCPbox is consolidating on MCP-first approach where LLMs create tools
programmatically via mcpbox_* MCP tools using python_code only.

This migration:
1. Logs warnings for existing api_config tools
2. Drops columns from tools table: api_config, execution_mode, source_operation_id, source_path, source_method
3. Drops columns from servers table: openapi_spec, import_source_url, source_type, generated_code
4. Drops columns from tool_versions table: api_config, execution_mode
5. Drops enum types: execution_mode, source_type

Revision ID: 0018
Revises: 0017_add_network_access_requests
Create Date: 2025-01-24
"""

import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic
revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    """Remove api_config and OpenAPI import related columns."""
    conn = op.get_bind()

    # Check for existing api_config tools and log warnings
    result = conn.execute(
        sa.text("""
            SELECT t.id, t.name, s.name as server_name
            FROM tools t
            JOIN servers s ON t.server_id = s.id
            WHERE t.execution_mode = 'api_config'
        """)
    )
    api_config_tools = result.fetchall()

    if api_config_tools:
        logger.warning("=" * 60)
        logger.warning("Found %d tools with api_config execution mode:", len(api_config_tools))
        for tool in api_config_tools:
            logger.warning("  - Tool '%s' on server '%s' (id: %s)", tool.name, tool.server_name, tool.id)
        logger.warning("These tools will no longer work after this migration.")
        logger.warning("Convert them to python_code mode before deploying.")
        logger.warning("=" * 60)

    # Check for servers with OpenAPI specs
    result = conn.execute(
        sa.text("""
            SELECT id, name FROM servers
            WHERE openapi_spec IS NOT NULL
        """)
    )
    openapi_servers = result.fetchall()

    if openapi_servers:
        logger.warning("Found %d servers with OpenAPI specs (will be removed):", len(openapi_servers))
        for server in openapi_servers:
            logger.warning("  - Server '%s' (id: %s)", server.name, server.id)

    # Drop columns from tools table
    op.drop_column("tools", "api_config")
    op.drop_column("tools", "execution_mode")
    op.drop_column("tools", "source_operation_id")
    op.drop_column("tools", "source_path")
    op.drop_column("tools", "source_method")

    # Drop columns from servers table
    op.drop_column("servers", "openapi_spec")
    op.drop_column("servers", "import_source_url")
    op.drop_column("servers", "source_type")
    op.drop_column("servers", "generated_code")

    # Drop columns from tool_versions table
    op.drop_column("tool_versions", "api_config")
    op.drop_column("tool_versions", "execution_mode")

    # Drop enum types (PostgreSQL specific)
    op.execute("DROP TYPE IF EXISTS execution_mode")
    op.execute("DROP TYPE IF EXISTS source_type")


def downgrade() -> None:
    """Re-add api_config and OpenAPI import columns."""
    # Re-create enum types
    execution_mode = postgresql.ENUM("api_config", "python_code", name="execution_mode", create_type=False)
    execution_mode.create(op.get_bind(), checkfirst=True)

    source_type = postgresql.ENUM("api_builder", name="source_type", create_type=False)
    source_type.create(op.get_bind(), checkfirst=True)

    # Re-add columns to tools table
    op.add_column(
        "tools",
        sa.Column("api_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "tools",
        sa.Column(
            "execution_mode",
            sa.Enum("api_config", "python_code", name="execution_mode"),
            nullable=False,
            server_default="api_config"
        )
    )
    op.add_column(
        "tools",
        sa.Column("source_operation_id", sa.String(255), nullable=True)
    )
    op.add_column(
        "tools",
        sa.Column("source_path", sa.String(1024), nullable=True)
    )
    op.add_column(
        "tools",
        sa.Column("source_method", sa.String(10), nullable=True)
    )

    # Re-add columns to servers table
    op.add_column(
        "servers",
        sa.Column("openapi_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "servers",
        sa.Column("import_source_url", sa.String(1024), nullable=True)
    )
    op.add_column(
        "servers",
        sa.Column(
            "source_type",
            sa.Enum("api_builder", name="source_type"),
            nullable=False,
            server_default="api_builder"
        )
    )
    op.add_column(
        "servers",
        sa.Column("generated_code", sa.Text(), nullable=True)
    )

    # Re-add columns to tool_versions table
    op.add_column(
        "tool_versions",
        sa.Column("api_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "tool_versions",
        sa.Column("execution_mode", sa.String(20), nullable=False, server_default="api_config")
    )
