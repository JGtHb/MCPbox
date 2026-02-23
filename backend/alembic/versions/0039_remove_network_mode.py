"""Remove network_mode column - always enforce allowlist.

Servers with no allowed_hosts are now truly isolated (empty array = no network
access).  This is more secure than the prior 'isolated' mode which passed None
to the sandbox (meaning no network restriction, only SSRF protection).

Revision ID: 0039
Revises: 0038
Create Date: 2026-02-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Convert NULL allowed_hosts to empty array for ALL servers
    op.execute("UPDATE servers SET allowed_hosts = '{}' WHERE allowed_hosts IS NULL")

    # 2. Make allowed_hosts NOT NULL with default empty array
    op.execute("ALTER TABLE servers ALTER COLUMN allowed_hosts SET DEFAULT '{}'")
    op.execute("ALTER TABLE servers ALTER COLUMN allowed_hosts SET NOT NULL")

    # 3. Drop network_mode column
    op.drop_column("servers", "network_mode")

    # 4. Drop the enum type
    op.execute("DROP TYPE IF EXISTS network_mode")


def downgrade() -> None:
    # Recreate the enum
    op.execute("CREATE TYPE network_mode AS ENUM ('isolated', 'allowlist')")

    # Re-add the column with default
    op.add_column(
        "servers",
        sa.Column(
            "network_mode",
            sa.Enum("isolated", "allowlist", name="network_mode"),
            nullable=False,
            server_default="isolated",
        ),
    )

    # Set network_mode based on whether allowed_hosts has entries
    op.execute(
        "UPDATE servers SET network_mode = 'allowlist' "
        "WHERE array_length(allowed_hosts, 1) IS NOT NULL "
        "AND array_length(allowed_hosts, 1) > 0"
    )

    # Make allowed_hosts nullable again and remove default
    op.execute("ALTER TABLE servers ALTER COLUMN allowed_hosts DROP NOT NULL")
    op.execute("ALTER TABLE servers ALTER COLUMN allowed_hosts DROP DEFAULT")

    # Set empty arrays back to NULL for 'isolated' servers
    op.execute("UPDATE servers SET allowed_hosts = NULL WHERE network_mode = 'isolated'")
