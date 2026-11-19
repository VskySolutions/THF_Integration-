from collections.abc import Sequence
import uuid

import sqlalchemy as sa

from alembic import op


revision: str = "20261116_0045"
down_revision: str | None = "20261116_0044"
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
                "id": uuid.UUID("d4e5f6a7-b8c9-4012-cdef-123456789012"),
                "identifier_unique_name": "MACONOMY_SAP_CONCUR_VENDOR_SYNC",
                "display_name": "SAP Concur to Maconomy vendor sync",
                "is_active": False,
                "source_system": "SAP Concur - Vendor",
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
            "'MACONOMY_SAP_CONCUR_VENDOR_SYNC'"
        )
    )
