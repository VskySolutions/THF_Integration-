"""Add is_emp_vendor_created column to paycor employee mapping log.

Revision ID: 20261021_0027
Revises: 20261018_0026
Create Date: 2026-10-22 00:00:00.000000

NOTE: This migration is created only. Execution (alembic upgrade head) is a
manual step performed by the user (Req[#1] WO[#1.4] manual steps).

NOTE (Rev 2): Originally drafted against paycor_integration_logs; amended
in place BEFORE execution (migration was never applied) to target
paycor_employee_mapping_log per user-approved placement revision — the
vendor outcome is per-employee state (1 row per employee), not event history.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261021_0027"
down_revision: Union[str, None] = "20261018_0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable enum column (values: EmpVendorCreationStatus in constants.py)
    # — records the employee-vendor creation outcome on the per-employee
    # mapping row. NULL means vendor outcome is not yet determined or
    # not applicable (e.g., mappings predating this feature).
    sa_enum = sa.Enum(
        "SUCCESS",
        "FAILURE",
        "SKIPPED",
        name="paycor_emp_vendor_creation_status",
    )
    # op.add_column does NOT auto-create PostgreSQL enum types
    # (unlike op.create_table, where SQLAlchemy's PG DDL compiler
    # emits CREATE TYPE). Create the type explicitly first;
    # checkfirst=True keeps the migration idempotent/safe on re-run.
    sa_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "paycor_employee_mapping_log",
        sa.Column(
            "is_emp_vendor_created",
            sa_enum,
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "paycor_employee_mapping_log",
        "is_emp_vendor_created",
    )
    op.drop_type("paycor_emp_vendor_creation_status")
