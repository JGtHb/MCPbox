"""Remove gateway_token from tunnel_configurations.

Gateway tokens were intended for bearer auth but Cloudflare MCP Server Portals
handles authentication directly, making gateway_token unnecessary.

Revision ID: 0013
Revises: 0012
Create Date: 2026-01-17

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("tunnel_configurations", "gateway_token")


def downgrade() -> None:
    op.add_column(
        "tunnel_configurations",
        sa.Column("gateway_token", sa.Text(), nullable=True),
    )
