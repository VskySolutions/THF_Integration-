"""Add SKIPPED label to paycor payroll integration status enum.

Revision ID: 20261027_0030
Revises: 20261027_0029
Create Date: 2026-10-27 00:00:00.000000

Adds 'SKIPPED' to the paycor_payroll_integration_status enum type
(created by 20261027_0029 with SUCCESS/FAILED only) so skipped journal
outcomes can be persisted (Req[#22] FR-11).

The pg_enum existence guard makes this revision idempotent and safe
whether or not 20261027_0029 has already been executed: if it has not,
alembic runs 0029 -> 0030 in chain order; if it has, only 0030 runs.

NOTE: This migration is created only. Execution (alembic upgrade head) is a
manual step performed by the user (Req[#22] manual steps). Requires
PostgreSQL >= 12 (ALTER TYPE ... ADD VALUE inside a transaction); the new
label is not used within this transaction.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261027_0030"
down_revision: Union[str, None] = "20261027_0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    already_present = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid "
            "WHERE t.typname = 'paycor_payroll_integration_status' "
            "AND e.enumlabel = 'SKIPPED'"
        )
    ).first()
    if already_present is None:
        conn.execute(
            sa.text(
                "ALTER TYPE paycor_payroll_integration_status"
                " ADD VALUE 'SKIPPED'"
            )
        )


def downgrade() -> None:
    # Intentional no-op: PG rejects removing an enum label that rows use,
    # and the whole type is dropped when 20261027_0029 downgrades.
    pass
