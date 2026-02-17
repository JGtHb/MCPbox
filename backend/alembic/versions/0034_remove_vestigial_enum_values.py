"""Remove vestigial enum values from server_status and network_mode.

Removes 'building' from server_status (vestigial from per-server container
architecture) and 'monitored'/'learning' from network_mode (never used).

Pre-release: no production databases exist, so we drop and recreate the enums.

Revision ID: 0034
Revises: 0033
Create Date: 2026-02-17
"""

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- server_status: remove 'building' ---
    # Change any rows that have 'building' to 'imported' (defensive)
    op.execute(
        "UPDATE servers SET status = 'imported' WHERE status = 'building'"
    )
    # Alter column to text temporarily
    op.execute("ALTER TABLE servers ALTER COLUMN status TYPE text")
    # Drop the old enum
    op.execute("DROP TYPE IF EXISTS server_status")
    # Recreate without 'building'
    op.execute(
        "CREATE TYPE server_status AS ENUM "
        "('imported', 'ready', 'running', 'stopped', 'error')"
    )
    # Convert column back to enum
    op.execute(
        "ALTER TABLE servers ALTER COLUMN status TYPE server_status "
        "USING status::server_status"
    )

    # --- network_mode: remove 'monitored' and 'learning' ---
    # Change any rows that have removed values to 'isolated' (defensive)
    op.execute(
        "UPDATE servers SET network_mode = 'isolated' "
        "WHERE network_mode IN ('monitored', 'learning')"
    )
    # Alter column to text temporarily
    op.execute("ALTER TABLE servers ALTER COLUMN network_mode TYPE text")
    # Drop the old enum
    op.execute("DROP TYPE IF EXISTS network_mode")
    # Recreate without 'monitored' and 'learning'
    op.execute(
        "CREATE TYPE network_mode AS ENUM ('isolated', 'allowlist')"
    )
    # Convert column back to enum
    op.execute(
        "ALTER TABLE servers ALTER COLUMN network_mode TYPE network_mode "
        "USING network_mode::network_mode"
    )


def downgrade() -> None:
    # --- server_status: re-add 'building' ---
    op.execute("ALTER TABLE servers ALTER COLUMN status TYPE text")
    op.execute("DROP TYPE IF EXISTS server_status")
    op.execute(
        "CREATE TYPE server_status AS ENUM "
        "('imported', 'building', 'ready', 'running', 'stopped', 'error')"
    )
    op.execute(
        "ALTER TABLE servers ALTER COLUMN status TYPE server_status "
        "USING status::server_status"
    )

    # --- network_mode: re-add 'monitored' and 'learning' ---
    op.execute("ALTER TABLE servers ALTER COLUMN network_mode TYPE text")
    op.execute("DROP TYPE IF EXISTS network_mode")
    op.execute(
        "CREATE TYPE network_mode AS ENUM "
        "('isolated', 'allowlist', 'monitored', 'learning')"
    )
    op.execute(
        "ALTER TABLE servers ALTER COLUMN network_mode TYPE network_mode "
        "USING network_mode::network_mode"
    )
