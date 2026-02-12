"""Add OAuth 2.0 Authorization Code Flow support.

This migration adds:
- oauth_grant_type enum and column for distinguishing client_credentials vs authorization_code
- oauth_authorization_url for the authorization endpoint
- oauth_state for CSRF protection during OAuth flow
- oauth_code_verifier for PKCE support

Revision ID: 0007
Revises: 0006
Create Date: 2026-01-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create the oauth_grant_type enum
    oauth_grant_type = sa.Enum(
        "client_credentials",
        "authorization_code",
        name="oauth_grant_type",
    )
    oauth_grant_type.create(op.get_bind(), checkfirst=True)

    # Add oauth_grant_type column
    op.add_column(
        "credentials",
        sa.Column(
            "oauth_grant_type",
            sa.Enum("client_credentials", "authorization_code", name="oauth_grant_type"),
            nullable=True,
            server_default="client_credentials",
        ),
    )

    # Add oauth_authorization_url column
    op.add_column(
        "credentials",
        sa.Column(
            "oauth_authorization_url",
            sa.String(1024),
            nullable=True,
        ),
    )

    # Add oauth_state column (for CSRF protection during flow)
    op.add_column(
        "credentials",
        sa.Column(
            "oauth_state",
            sa.String(128),
            nullable=True,
        ),
    )

    # Add oauth_code_verifier column (for PKCE)
    op.add_column(
        "credentials",
        sa.Column(
            "oauth_code_verifier",
            sa.String(128),
            nullable=True,
        ),
    )

    # Set default grant type for existing oauth2 credentials
    op.execute(
        """
        UPDATE credentials
        SET oauth_grant_type = 'client_credentials'
        WHERE auth_type = 'oauth2' AND oauth_grant_type IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("credentials", "oauth_code_verifier")
    op.drop_column("credentials", "oauth_state")
    op.drop_column("credentials", "oauth_authorization_url")
    op.drop_column("credentials", "oauth_grant_type")

    # Drop the enum type
    oauth_grant_type = sa.Enum(
        "client_credentials",
        "authorization_code",
        name="oauth_grant_type",
    )
    oauth_grant_type.drop(op.get_bind(), checkfirst=True)
