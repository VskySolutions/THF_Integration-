"""Register the Maconomy-first CaseWare Cloud sync service.

Revision ID: 20260916_0010
Revises: 20260916_0009
"""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa

from alembic import op


revision: str = "20260916_0010"
down_revision: str | None = "20260916_0009"
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
                "id": uuid.UUID("8edc60c7-98f5-4d57-8fb1-cb5e0edc06fd"),
                "identifier_unique_name": "MACONOMY_CASEWARE_CLOUD_SYNC",
                "display_name": "Maconomy to CaseWare Cloud sync",
                "is_active": False,
                "source_system": "Maconomy",
                "target_system": "CaseWare Cloud",
                "is_deleted": False,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM integration_service "
            "WHERE identifier_unique_name = "
            "'MACONOMY_CASEWARE_CLOUD_SYNC'"
        )
    )
