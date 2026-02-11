"""Add missing partial unique indexes for duplicate request prevention.

The model definitions in module_request.py and network_access_request.py
declare partial unique indexes to prevent duplicate pending requests,
but migrations 0016 and 0017 never created them.

Revision ID: 0023
Revises: 0022
Create Date: 2026-02-06

"""

from alembic import op

# revision identifiers
revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add partial unique index on module_requests to prevent duplicate pending requests
    # for the same (tool_id, module_name) combination
    op.execute(
        """
        CREATE UNIQUE INDEX ix_module_requests_pending_unique
        ON module_requests (tool_id, module_name)
        WHERE status = 'pending'
        """
    )

    # Add partial unique index on network_access_requests to prevent duplicate pending
    # requests for the same (tool_id, host, port) combination.
    # Uses COALESCE(port, 0) to handle NULL port values correctly in the unique constraint
    # (PostgreSQL treats NULLs as distinct, so without COALESCE, multiple NULL-port
    # requests for the same tool+host would bypass the constraint)
    op.execute(
        """
        CREATE UNIQUE INDEX ix_network_access_requests_pending_unique
        ON network_access_requests (tool_id, host, COALESCE(port, 0))
        WHERE status = 'pending'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_network_access_requests_pending_unique",
        table_name="network_access_requests",
    )
    op.drop_index(
        "ix_module_requests_pending_unique",
        table_name="module_requests",
    )
