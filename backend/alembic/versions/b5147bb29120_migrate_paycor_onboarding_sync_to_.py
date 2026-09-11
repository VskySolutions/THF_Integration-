"""Migrate Paycor onboarding sync to employee sync.

Revision ID: b5147bb29120
Revises: f55df969c71e
Create Date: 2026-09-09 19:12:33.639331
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b5147bb29120"
down_revision: Union[str, None] = "f55df969c71e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM paycor_integration_logs"))
    op.execute(sa.text("DELETE FROM paycor_employee_mapping_log"))

    op.add_column("paycor_employee_mapping_log", sa.Column("paycor_employee_id", sa.Uuid(), nullable=False))
    op.alter_column("paycor_employee_mapping_log", "paycor_employee_number", existing_type=sa.Text(), nullable=False)
    op.drop_constraint("uq_paycor_mapping_legal_entity_onboarding_employee", "paycor_employee_mapping_log", type_="unique")
    op.create_unique_constraint("uq_paycor_mapping_legal_entity_employee", "paycor_employee_mapping_log", ["paycor_legal_entity_id", "paycor_employee_id"])
    op.drop_column("paycor_employee_mapping_log", "employee_status")
    op.drop_column("paycor_employee_mapping_log", "paycor_onboarding_employee_id")

    op.add_column("paycor_integration_logs", sa.Column("paycor_employee_id", sa.Uuid(), nullable=False))
    op.add_column("paycor_integration_logs", sa.Column("paycor_employee_number", sa.Text(), nullable=True))
    op.drop_column("paycor_integration_logs", "paycor_onboarding_employee_id")

    op.execute(sa.text("DROP TYPE IF EXISTS paycor_employee_status"))

    op.execute(sa.text("UPDATE integration_service SET identifier_unique_name = 'PAYCOR_SYNC_EMPLOYEES', display_name = 'Sync Paycor employees with Maconomy', updated_on_utc = now() WHERE identifier_unique_name = 'PAYCOR_SYNC_ONBOARDING_EMPLOYEES'"))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM paycor_integration_logs"))
    op.execute(sa.text("DELETE FROM paycor_employee_mapping_log"))

    op.execute(sa.text("CREATE TYPE paycor_employee_status AS ENUM ('INVITED', 'HIRED')"))

    op.add_column("paycor_integration_logs", sa.Column("paycor_onboarding_employee_id", sa.Uuid(), nullable=False))
    op.drop_column("paycor_integration_logs", "paycor_employee_number")
    op.drop_column("paycor_integration_logs", "paycor_employee_id")

    op.add_column("paycor_employee_mapping_log", sa.Column("paycor_onboarding_employee_id", sa.Uuid(), nullable=False))
    op.add_column("paycor_employee_mapping_log", sa.Column("employee_status", postgresql.ENUM("INVITED", "HIRED", name="paycor_employee_status", create_type=False), nullable=False))
    op.drop_constraint("uq_paycor_mapping_legal_entity_employee", "paycor_employee_mapping_log", type_="unique")
    op.create_unique_constraint("uq_paycor_mapping_legal_entity_onboarding_employee", "paycor_employee_mapping_log", ["paycor_legal_entity_id", "paycor_onboarding_employee_id"])
    op.alter_column("paycor_employee_mapping_log", "paycor_employee_number", existing_type=sa.Text(), nullable=True)
    op.drop_column("paycor_employee_mapping_log", "paycor_employee_id")

    op.execute(sa.text("UPDATE integration_service SET identifier_unique_name = 'PAYCOR_SYNC_ONBOARDING_EMPLOYEES', display_name = 'Sync Paycor onboarding employees with Maconomy', updated_on_utc = now() WHERE identifier_unique_name = 'PAYCOR_SYNC_EMPLOYEES'"))