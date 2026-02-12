"""Remove unused server fields (repo_url, repo_branch, commit_hash).

These fields were intended for git-based imports but that feature was never
implemented. All servers use source_type='api_builder'.

Revision ID: 0014
Revises: 0013
Create Date: 2026-01-18

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("servers", "repo_url")
    op.drop_column("servers", "repo_branch")
    op.drop_column("servers", "commit_hash")


def downgrade() -> None:
    op.add_column(
        "servers",
        sa.Column("commit_hash", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "servers",
        sa.Column("repo_branch", sa.String(length=255), nullable=False, server_default="main"),
    )
    op.add_column(
        "servers",
        sa.Column("repo_url", sa.String(length=1024), nullable=True),
    )
