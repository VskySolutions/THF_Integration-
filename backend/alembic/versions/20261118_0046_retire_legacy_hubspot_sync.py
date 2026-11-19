"""Retire the deprecated Maconomy to HubSpot integration service.

Revision ID: 20261118_0046
Revises: 20261116_0045
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261118_0046"
down_revision: str | None = "20261116_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE integration_service "
            "SET is_active = false, is_deleted = true "
            "WHERE identifier_unique_name = 'MACONOMY_HUBSPOT_SYNC'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE integration_service "
            "SET is_deleted = false "
            "WHERE identifier_unique_name = 'MACONOMY_HUBSPOT_SYNC'"
        )
    )
