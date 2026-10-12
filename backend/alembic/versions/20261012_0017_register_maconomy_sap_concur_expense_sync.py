"""Register the Maconomy to SAP Concur expense sync service.

Revision ID: 20261012_0017
Revises: 20261006_0016
"""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa

from alembic import op


revision: str = "20261012_0017"
down_revision: str | None = "20261006_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.bulk_insert(
        sa.table(
            "integration_service",
            sa.column("id", sa.Uuid()),
            sa.column("identifier_unique_name", sa.Text()),
            sa.column("display_name", sa.Text()),
            sa.column("is_active", sa.Boolean()),
            sa.column("source_system", sa.Text()),
            sa.column("target_system", sa.Text()),
            sa.column("is_deleted", sa.Boolean()),
        ),
        [
            {
                "id": uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
                "identifier_unique_name": "MACONOMY_SAP_CONCUR_EXPENSE_SYNC",
                "display_name": "Maconomy to SAP Concur expense sync",
                "is_active": False,
                "source_system": "SAP Concur- Expense",
                "target_system": "Maconomy",
                "is_deleted": False,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM integration_service "
            "WHERE identifier_unique_name = "
            "'MACONOMY_SAP_CONCUR_EXPENSE_SYNC'"
        )
    )
