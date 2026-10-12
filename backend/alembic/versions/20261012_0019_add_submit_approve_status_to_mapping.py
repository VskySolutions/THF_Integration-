"""Add submitted/approved status columns to sap concur mapping.

Revision ID: 20261012_0019
Revises: 20261012_0018
Create Date: 2026-10-12 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261012_0019"
down_revision: Union[str, None] = "20261012_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sap_concur_expensesheet_expensereport_mapping",
        sa.Column(
            "submitted",
            postgresql.ENUM(
                "SUCCESS",
                "FAILED",
                "SKIPPED",
                name="sap_concur_integration_status",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "sap_concur_expensesheet_expensereport_mapping",
        sa.Column(
            "approved",
            postgresql.ENUM(
                "SUCCESS",
                "FAILED",
                "SKIPPED",
                name="sap_concur_integration_status",
                create_type=False,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sap_concur_expensesheet_expensereport_mapping", "approved")
    op.drop_column("sap_concur_expensesheet_expensereport_mapping", "submitted")
