"""Add RETRY_CREATE value to sap concur integration action enum.

Revision ID: 20261014_0024
Revises: 20261013_0023
Create Date: 2026-10-14 00:00:00.000000

NOTE: This migration is created only. Execution (alembic upgrade head) is a
manual step performed by the user (Req[#16] WO[#16.3] manual steps).

Follow-up to the applied revision 20261013_0023, which added the legacy 'RETRY'
value (now superseded). Adds RETRY_CREATE so retry attempts are identifiable in
sap_concur_integration_logs.action (Req[#16] FR-21, user directive 2026-10-14:
action value renamed RETRY -> RETRY_CREATE). IF NOT EXISTS keeps the migration
idempotent. The legacy 'RETRY' value is intentionally retained in the enum type:
PostgreSQL has no ALTER TYPE ... DROP VALUE.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20261014_0024"
down_revision: Union[str, None] = "20261013_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the new value to the PostgreSQL enum type used by
    # sap_concur_integration_logs.action. IF NOT EXISTS keeps it idempotent.
    op.execute(
        "ALTER TYPE sap_concur_integration_action "
        "ADD VALUE IF NOT EXISTS 'RETRY_CREATE'"
    )


def downgrade() -> None:
    # The 'RETRY_CREATE' enum value is intentionally retained:
    # PostgreSQL has no ALTER TYPE ... DROP VALUE. Removing it would require
    # recreating the enum type (out of scope; documented limitation).
    pass
