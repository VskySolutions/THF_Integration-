"""Create integration service master table and seed service switches.

Revision ID: 20260831_0008
Revises: a8c4bafd2f52
Create Date: 2026-08-31
"""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa

from alembic import op

revision: str = "20260831_0008"
down_revision: str | None = 'a8c4bafd2f52'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    integration_service = op.create_table(
        "integration_service",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identifier_unique_name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("source_system", sa.Text(), nullable=True),
        sa.Column("target_system", sa.Text(), nullable=True),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_service")),
        sa.UniqueConstraint(
            "identifier_unique_name",
            name=op.f("uq_integration_service_identifier_unique_name"),
        ),
    )

    op.bulk_insert(
        integration_service,
        [
            {
                "id": uuid.UUID("f583bc82-1ab5-4b54-aef7-bc30da975b56"),
                "identifier_unique_name": "CASEWARE_CREATE_ENGAGEMENT",
                "display_name": "Create CaseWare engagement",
                "is_active": False,
                "source_system": "Maconomy",
                "target_system": "CaseWare Cloud",
                "is_deleted": False,
            },
            {
                "id": uuid.UUID("2f5f715c-0163-4a40-861e-ee6605dc2d3e"),
                "identifier_unique_name": "CASEWARE_SYNC_CREATED_ENGAGEMENTS",
                "display_name": "Sync created Maconomy engagements with CaseWare",
                "is_active": False,
                "source_system": "Maconomy",
                "target_system": "CaseWare Cloud",
                "is_deleted": False,
            },
            {
                "id": uuid.UUID("355162c2-ce62-4637-8985-f637b8070c06"),
                "identifier_unique_name": "CASEWARE_UPDATE_ENGAGEMENT",
                "display_name": "Update CaseWare engagement",
                "is_active": False,
                "source_system": "Maconomy",
                "target_system": "CaseWare Cloud",
                "is_deleted": False,
            },
            {
                "id": uuid.UUID("21a3769b-4389-4c3a-a5f1-9b093396f59f"),
                "identifier_unique_name": "CASEWARE_SYNC_UPDATED_ENGAGEMENTS",
                "display_name": "Sync updated Maconomy engagements with CaseWare",
                "is_active": False,
                "source_system": "Maconomy",
                "target_system": "CaseWare Cloud",
                "is_deleted": False,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("integration_service")
