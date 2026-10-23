"""Add maconomy_emp_vendor_number column to paycor employee mapping log.

Revision ID: 20261021_0028
Revises: 20261021_0027
Create Date: 2026-10-22 00:00:00.000000

NOTE: This migration is created only. Execution (alembic upgrade head) is a
manual step performed by the user (Req[#1] WO[#1.5] manual steps).

Plain nullable Text column (no PostgreSQL enum type involved). Predecessor
revision 20261021_0027 has already been applied — this is the standalone
next migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261021_0028"
down_revision: Union[str, None] = "20261021_0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable Text column — stores the Maconomy employee-vendor number
    # (vendornumber from the vendor-creation response) on the per-employee
    # mapping row. NULL = vendor not created / outcome not applicable.
    op.add_column(
        "paycor_employee_mapping_log",
        sa.Column(
            "maconomy_emp_vendor_number",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "paycor_employee_mapping_log",
        "maconomy_emp_vendor_number",
    )
