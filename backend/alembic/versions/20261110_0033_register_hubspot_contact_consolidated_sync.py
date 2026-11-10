"""Register the consolidated Maconomy to HubSpot contact sync service.

Revision ID: 20261110_0033
Revises: 20261109_0032

This migration is setup only. It must be executed manually by the user.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261110_0033"
down_revision: str | None = "20261109_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SERVICE_IDENTIFIER = "MACONOMY_HUBSPOT_CONTACT_CONSOLIDATED_SYNC"

integration_service = sa.table(
    "integration_service",
    sa.column("id", sa.Uuid()),
    sa.column("identifier_unique_name", sa.Text()),
    sa.column("display_name", sa.Text()),
    sa.column("is_active", sa.Boolean()),
    sa.column("source_system", sa.Text()),
    sa.column("target_system", sa.Text()),
    sa.column("is_deleted", sa.Boolean()),
)


def upgrade() -> None:
    op.bulk_insert(
        integration_service,
        [
            {
                "id": uuid.UUID("81624db7-796d-43de-a7fc-b5467651cc7e"),
                "identifier_unique_name": SERVICE_IDENTIFIER,
                "display_name": "Maconomy to HubSpot consolidated contact sync",
                "is_active": False,
                "source_system": "Maconomy",
                "target_system": "HubSpot",
                "is_deleted": False,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        integration_service.delete().where(
            integration_service.c.identifier_unique_name == SERVICE_IDENTIFIER
        )
    )
