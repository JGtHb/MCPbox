"""consolidate approval sources

Make request tables the single source of truth for network hosts and modules.
Add server_id column and make tool_id nullable on both request tables.
Backfill server_id from tool relationships and create records for manually-added hosts/modules.

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- network_access_requests ---

    # 1. Add server_id column (nullable FK)
    op.add_column(
        "network_access_requests",
        sa.Column("server_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_network_access_requests_server_id",
        "network_access_requests",
        "servers",
        ["server_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 2. Backfill server_id from tool.server_id
    op.execute(
        """
        UPDATE network_access_requests nar
        SET server_id = t.server_id
        FROM tools t
        WHERE nar.tool_id = t.id AND nar.server_id IS NULL
        """
    )

    # 3. Make tool_id nullable
    op.alter_column("network_access_requests", "tool_id", nullable=True)

    # 4. Replace unique partial index
    op.drop_index(
        "ix_network_access_requests_pending_unique",
        table_name="network_access_requests",
    )
    # For LLM requests (tool_id IS NOT NULL): unique on (tool_id, host, port)
    op.execute(
        """
        CREATE UNIQUE INDEX ix_nar_pending_tool_unique
        ON network_access_requests (tool_id, host, COALESCE(port, 0))
        WHERE status = 'pending' AND tool_id IS NOT NULL
        """
    )
    # For admin requests (tool_id IS NULL): unique on (server_id, host, port)
    op.execute(
        """
        CREATE UNIQUE INDEX ix_nar_pending_admin_unique
        ON network_access_requests (server_id, host, COALESCE(port, 0))
        WHERE status = 'pending' AND tool_id IS NULL
        """
    )

    # 5. Create records for manually-added hosts that have no approved request
    op.execute(
        """
        INSERT INTO network_access_requests
            (id, server_id, tool_id, host, port, justification, requested_by,
             status, reviewed_at, reviewed_by, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            s.id,
            NULL,
            h.host,
            NULL,
            'Pre-existing host (migrated)',
            'admin',
            'approved',
            NOW(),
            'system-migration',
            NOW(),
            NOW()
        FROM servers s, unnest(s.allowed_hosts) AS h(host)
        WHERE s.allowed_hosts IS NOT NULL
          AND array_length(s.allowed_hosts, 1) > 0
          AND NOT EXISTS (
              SELECT 1 FROM network_access_requests nar2
              JOIN tools t ON nar2.tool_id = t.id
              WHERE nar2.host = h.host
                AND t.server_id = s.id
                AND nar2.status = 'approved'
          )
        """
    )

    # --- module_requests ---

    # 1. Add server_id column (nullable FK)
    op.add_column(
        "module_requests",
        sa.Column("server_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_module_requests_server_id",
        "module_requests",
        "servers",
        ["server_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 2. Backfill server_id from tool.server_id
    op.execute(
        """
        UPDATE module_requests mr
        SET server_id = t.server_id
        FROM tools t
        WHERE mr.tool_id = t.id AND mr.server_id IS NULL
        """
    )

    # 3. Make tool_id nullable
    op.alter_column("module_requests", "tool_id", nullable=True)

    # 4. Replace unique partial index
    op.drop_index(
        "ix_module_requests_pending_unique",
        table_name="module_requests",
    )
    # For LLM requests (tool_id IS NOT NULL)
    op.execute(
        """
        CREATE UNIQUE INDEX ix_mr_pending_tool_unique
        ON module_requests (tool_id, module_name)
        WHERE status = 'pending' AND tool_id IS NOT NULL
        """
    )
    # For admin requests (tool_id IS NULL, global)
    op.execute(
        """
        CREATE UNIQUE INDEX ix_mr_pending_admin_unique
        ON module_requests (module_name)
        WHERE status = 'pending' AND tool_id IS NULL
        """
    )

    # 5. Create records for custom modules that have no approved request
    op.execute(
        """
        INSERT INTO module_requests
            (id, server_id, tool_id, module_name, justification, requested_by,
             status, reviewed_at, reviewed_by, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            NULL,
            NULL,
            m.module_name,
            'Pre-existing module (migrated)',
            'admin',
            'approved',
            NOW(),
            'system-migration',
            NOW(),
            NOW()
        FROM (
            SELECT unnest(allowed_modules) AS module_name
            FROM global_config
            WHERE allowed_modules IS NOT NULL
            LIMIT 1
        ) AS m
        WHERE NOT EXISTS (
            SELECT 1 FROM module_requests mr2
            WHERE mr2.module_name = m.module_name
              AND mr2.status = 'approved'
        )
        """
    )


def downgrade() -> None:
    # --- module_requests ---

    # Remove admin-originated records (tool_id IS NULL)
    op.execute("DELETE FROM module_requests WHERE tool_id IS NULL")

    # Restore unique partial index
    op.drop_index("ix_mr_pending_admin_unique", table_name="module_requests")
    op.drop_index("ix_mr_pending_tool_unique", table_name="module_requests")
    op.execute(
        """
        CREATE UNIQUE INDEX ix_module_requests_pending_unique
        ON module_requests (tool_id, module_name)
        WHERE status = 'pending'
        """
    )

    # Make tool_id NOT NULL again
    op.alter_column("module_requests", "tool_id", nullable=False)

    # Drop server_id column
    op.drop_constraint("fk_module_requests_server_id", "module_requests", type_="foreignkey")
    op.drop_column("module_requests", "server_id")

    # --- network_access_requests ---

    # Remove admin-originated records (tool_id IS NULL)
    op.execute("DELETE FROM network_access_requests WHERE tool_id IS NULL")

    # Restore unique partial index
    op.drop_index("ix_nar_pending_admin_unique", table_name="network_access_requests")
    op.drop_index("ix_nar_pending_tool_unique", table_name="network_access_requests")
    op.execute(
        """
        CREATE UNIQUE INDEX ix_network_access_requests_pending_unique
        ON network_access_requests (tool_id, host, COALESCE(port, 0))
        WHERE status = 'pending'
        """
    )

    # Make tool_id NOT NULL again
    op.alter_column("network_access_requests", "tool_id", nullable=False)

    # Drop server_id column
    op.drop_constraint(
        "fk_network_access_requests_server_id",
        "network_access_requests",
        type_="foreignkey",
    )
    op.drop_column("network_access_requests", "server_id")
