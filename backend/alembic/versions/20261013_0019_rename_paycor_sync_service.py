"""Rename the Paycor employee-sync integration service.

Revision ID: 20261013_0019
Revises: 20261012_0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261013_0019"
down_revision: str | None = "20261012_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


integration_service = sa.table(
    "integration_service",
    sa.column("identifier_unique_name", sa.Text()),
)

OLD_IDENTIFIER = "PAYCOR_SYNC_ONBOARDING_EMPLOYEES"
NEW_IDENTIFIER = "PAYCOR_SYNC_EMPLOYEES"


def upgrade() -> None:
    op.execute(
        integration_service.update()
        .where(integration_service.c.identifier_unique_name == OLD_IDENTIFIER)
        .values(identifier_unique_name=NEW_IDENTIFIER)
    )


def downgrade() -> None:
    op.execute(
        integration_service.update()
        .where(integration_service.c.identifier_unique_name == NEW_IDENTIFIER)
        .values(identifier_unique_name=OLD_IDENTIFIER)
    )
