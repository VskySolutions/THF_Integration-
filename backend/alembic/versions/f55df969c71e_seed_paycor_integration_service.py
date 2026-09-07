"""Seed Paycor integration service.

Revision ID: f55df969c71e
Revises: 8b29928452bc
Create Date: 2026-09-04 20:30:54.176328
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f55df969c71e"
down_revision: str | None = "8b29928452bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
                "id": uuid.UUID(
                    "bd22e0d8-c09a-4506-88ae-df7f1ed682fc"
                ),
                "identifier_unique_name": (
                    "PAYCOR_SYNC_ONBOARDING_EMPLOYEES"
                ),
                "display_name": (
                    "Sync Paycor onboarding employees "
                    "with Maconomy"
                ),
                "is_active": False,
                "source_system": "Paycor",
                "target_system": "Maconomy",
                "is_deleted": False,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        integration_service.delete().where(
            integration_service.c.identifier_unique_name
            == "PAYCOR_SYNC_ONBOARDING_EMPLOYEES"
        )
    )