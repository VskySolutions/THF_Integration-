"""Register the Maconomy to SAP Concur engagements & tasks sync service.

Revision ID: 20261112_0039
Revises: 20261112_0038
"""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa

from alembic import op


revision: str = "20261112_0043"
down_revision: str | None = "20261112_0042"
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
                "id": uuid.UUID("c3d4e5f6-a7b8-8901-cdef-123456789012"),
                "identifier_unique_name": (
                    "MACONOMY_SAP_CONCUR_ENGAGEMENTS_AND_TASKS_SYNC"
                ),
                "display_name": (
                    "Maconomy to SAP Concur engagements & tasks sync"
                ),
                "is_active": False,
                "source_system": "Maconomy",
                "target_system": "SAP Concur - Engagement & Task",
                "is_deleted": False,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM integration_service "
            "WHERE identifier_unique_name = "
            "'MACONOMY_SAP_CONCUR_ENGAGEMENTS_AND_TASKS_SYNC'"
        )
    )
