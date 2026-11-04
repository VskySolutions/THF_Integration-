"""Register the Maconomy to Paycor timesheet sync service.

Revision ID: 20261102_0031
Revises: 20261102_0030
Create Date: 2026-11-02
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261102_0031"
down_revision: str | None = "20261102_0030"
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
                    "b3729466-f47d-43a4-a8ba-b8d540e1c346"
                ),
                "identifier_unique_name": (
                    "PAYCOR_SYNC_TIMESHEETS"
                ),
                "display_name": (
                    "Sync Maconomy timesheets with Paycor"
                ),
                "is_active": False,
                "source_system": "Maconomy",
                "target_system": "Paycor",
                "is_deleted": False,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        integration_service.delete().where(
            integration_service.c.identifier_unique_name
            == "PAYCOR_SYNC_TIMESHEETS"
        )
    )
