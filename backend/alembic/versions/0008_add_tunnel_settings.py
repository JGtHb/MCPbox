"""Add tunnel configuration settings.

This migration adds default settings for named tunnel support:
- tunnel_mode: quick or named
- cloudflare_tunnel_token: encrypted token for named tunnels
- gateway_token_persistent: encrypted persisted gateway token

Revision ID: 0008
Revises: 0007
Create Date: 2026-01-15

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Insert tunnel-related settings
    op.execute(
        """
        INSERT INTO settings (id, key, value, encrypted, description)
        VALUES
            (gen_random_uuid(), 'tunnel_mode', 'quick', false, 'Tunnel mode: quick (random URL) or named (persistent URL)'),
            (gen_random_uuid(), 'cloudflare_tunnel_token', NULL, true, 'Cloudflare tunnel token for named tunnel mode'),
            (gen_random_uuid(), 'gateway_token_persistent', NULL, true, 'Persisted gateway token for named tunnels')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM settings
        WHERE key IN ('tunnel_mode', 'cloudflare_tunnel_token', 'gateway_token_persistent')
        """
    )
