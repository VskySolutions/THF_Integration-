"""Register the Maconomy to SAP Concur invoice sync service.

Revision ID: 20261112_0037
Revises: 20261111_0035
"""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa

from alembic import op


revision: str = "20261112_0041"
down_revision: str | None = "20261111_0040"
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
                "id": uuid.UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901"),
                "identifier_unique_name": "MACONOMY_SAP_CONCUR_INVOICE_SYNC",
                "display_name": "Maconomy to SAP Concur invoice sync",
                "is_active": False,
                "source_system": "SAP Concur- Invoice",
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
            "'MACONOMY_SAP_CONCUR_INVOICE_SYNC'"
        )
    )
