"""Give SAP Concur invoice v2 its own log enums and service registration."""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "20261121_0049"
down_revision: str | None = "20261121_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_TYPE = postgresql.ENUM(
    "SUCCESS",
    "FAILED",
    "SKIPPED",
    "PARTIALLY_SUCCESS",
    name="sap_concur_invoice_integration_status_v2",
    create_type=False,
)
_ACTION_TYPE = postgresql.ENUM(
    "CREATE",
    "UPDATE",
    "RETRY_CREATE",
    name="sap_concur_invoice_integration_action_v2",
    create_type=False,
)
_SERVICE_ID = uuid.UUID("63ee5a64-3cc3-427d-bad6-54edba9ced46")


def upgrade() -> None:
    bind = op.get_bind()
    _STATUS_TYPE.create(bind, checkfirst=False)
    _ACTION_TYPE.create(bind, checkfirst=False)
    op.execute(
        """
        ALTER TABLE sap_concur_invoice_integration_logs_v2
            ALTER COLUMN status TYPE sap_concur_invoice_integration_status_v2
                USING status::text::sap_concur_invoice_integration_status_v2,
            ALTER COLUMN action TYPE sap_concur_invoice_integration_action_v2
                USING action::text::sap_concur_invoice_integration_action_v2
        """
    )

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
                "id": _SERVICE_ID,
                "identifier_unique_name": "MACONOMY_SAP_CONCUR_INVOICE_V2_SYNC",
                "display_name": "SAP Concur to Maconomy invoice sync v2",
                "is_active": False,
                "source_system": "SAP Concur- Invoice",
                "target_system": "Maconomy",
                "is_deleted": False,
            }
        ],
    )


def downgrade() -> None:
    service = sa.table("integration_service", sa.column("id", sa.Uuid()))
    op.execute(service.delete().where(service.c.id == _SERVICE_ID))
    op.execute(
        """
        ALTER TABLE sap_concur_invoice_integration_logs_v2
            ALTER COLUMN status TYPE sap_concur_invoice_integration_status
                USING status::text::sap_concur_invoice_integration_status,
            ALTER COLUMN action TYPE sap_concur_invoice_integration_action
                USING action::text::sap_concur_invoice_integration_action
        """
    )
    bind = op.get_bind()
    _ACTION_TYPE.drop(bind, checkfirst=False)
    _STATUS_TYPE.drop(bind, checkfirst=False)
