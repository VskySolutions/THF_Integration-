"""Register the Maconomy to CCH/XCM task-mapping service.

Revision ID: 20260921_0012
Revises: 20260921_0011
"""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa

from alembic import op


revision: str = "20260921_0012"
down_revision: str | None = "20260921_0011"
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
                "id": uuid.UUID("85c3d51b-3f93-40a1-9e31-e6952355e32f"),
                "identifier_unique_name": "MACONOMY_CCH_XCM_TASK_MAPPING",
                "display_name": "Maconomy to CCH/XCM task mapping",
                "is_active": False,
                "source_system": "Maconomy",
                "target_system": "CCH/XCM",
                "is_deleted": False,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM integration_service "
            "WHERE identifier_unique_name = "
            "'MACONOMY_CCH_XCM_TASK_MAPPING'"
        )
    )
