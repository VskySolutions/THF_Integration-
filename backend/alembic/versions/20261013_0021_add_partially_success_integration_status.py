"""Add PARTIALLY_SUCCESS status and processing_stage column to sap concur integration logs.

Revision ID: 20261013_0021
Revises: 20261012_0020
Create Date: 2026-10-13 00:00:00.000000

NOTE: This migration is created only. Execution (alembic upgrade head) is a
manual step performed by the user (Req[#15] WO[#15.1] manual steps).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261013_0021"
down_revision: Union[str, None] = "20261012_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the new value to the shared PostgreSQL enum type used by
    # sap_concur_integration_logs.status and the mapping submitted/approved
    # columns. IF NOT EXISTS keeps the migration idempotent.
    op.execute(
        "ALTER TYPE sap_concur_integration_status "
        "ADD VALUE IF NOT EXISTS 'PARTIALLY_SUCCESS'"
    )
    # Nullable Text column (not a PG enum) — records the workflow stage that
    # produced the logged outcome (values: ProcessingStage in constants.py).
    op.add_column(
        "sap_concur_integration_logs",
        sa.Column("processing_stage", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sap_concur_integration_logs", "processing_stage")
    # The 'PARTIALLY_SUCCESS' enum value is intentionally retained:
    # PostgreSQL has no ALTER TYPE ... DROP VALUE. Removing it would require
    # recreating the enum type (out of scope; documented limitation).
