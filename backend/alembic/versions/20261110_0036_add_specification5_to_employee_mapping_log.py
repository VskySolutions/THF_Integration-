"""Add is_spec5_created and maconomy_spec5_name to paycor_employee_mapping_log.

Revision ID: 20261110_0036
Revises: 20261102_0035
Create Date: 2026-11-10 17:58:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261110_0036"
down_revision: Union[str, None] = "20261102_0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    sa_enum = sa.Enum(
        "SUCCESS",
        "FAILURE",
        "SKIPPED",
        name="paycor_spec5_creation_status",
    )
    sa_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "paycor_employee_mapping_log",
        sa.Column(
            "is_spec5_created",
            sa_enum,
            nullable=True,
        ),
    )
    op.add_column(
        "paycor_employee_mapping_log",
        sa.Column(
            "maconomy_spec5_name",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "paycor_employee_mapping_log",
        "maconomy_spec5_name",
    )
    op.drop_column(
        "paycor_employee_mapping_log",
        "is_spec5_created",
    )
    op.execute("DROP TYPE IF EXISTS paycor_spec5_creation_status")

