"""Add is_sap_concur_created and sap_concur_user_id to paycor_employee_mapping_log.

Revision ID: 20261111_0036
Revises: 20261110_0035
Create Date: 2026-11-11 19:06:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261111_0034"
down_revision: Union[str, None] = "20261110_0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    sa_enum = sa.Enum(
        "SUCCESS",
        "FAILURE",
        "SKIPPED",
        name="paycor_sap_concur_user_creation_status",
    )
    sa_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "paycor_employee_mapping_log",
        sa.Column(
            "is_sap_concur_created",
            sa_enum,
            nullable=True,
        ),
    )
    op.add_column(
        "paycor_employee_mapping_log",
        sa.Column(
            "sap_concur_user_id",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "paycor_employee_mapping_log",
        "sap_concur_user_id",
    )
    op.drop_column(
        "paycor_employee_mapping_log",
        "is_sap_concur_created",
    )
    op.execute("DROP TYPE IF EXISTS paycor_sap_concur_user_creation_status")

