"""Remove helper_code column from servers table.

The helper_code feature (shared Python code across all tools in a server)
was never exposed via API or UI after server creation. Removing as part
of pre-release cleanup.

Revision ID: 0035
Revises: 0034
Create Date: 2026-02-17

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("servers", "helper_code")


def downgrade() -> None:
    import sqlalchemy as sa

    op.add_column(
        "servers",
        sa.Column("helper_code", sa.Text(), nullable=True),
    )
