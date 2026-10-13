"""Add details JSONB column to sap concur integration logs.

Revision ID: 20261013_0022
Revises: 20261013_0021
Create Date: 2026-10-13 00:00:00.000000

NOTE: This migration is created only. Execution (alembic upgrade head) is a
manual step performed by the user (Req[#15] WO[#15.3] manual steps).

The nullable `details` JSONB column stores a structured per-report stage
outcome snapshot (expense_sheet / expense_lines / submission / approval),
following the pattern used by xcm_cch_client_scoped_integration run logs.
Nullable -> no impact on existing rows.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261013_0022"
down_revision: Union[str, None] = "20261013_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sap_concur_integration_logs",
        sa.Column("details", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sap_concur_integration_logs", "details")
