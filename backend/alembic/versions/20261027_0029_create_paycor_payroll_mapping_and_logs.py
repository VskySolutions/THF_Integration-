"""Create paycor payroll journal mapping and integration logs tables.

Revision ID: 20261027_0029
Revises: 20261021_0028
Create Date: 2026-10-27 00:00:00.000000

NOTE: This migration is created only. Execution (alembic upgrade head) is a
manual step performed by the user (Req[#22] WO[#22.2] manual steps).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261027_0029"
down_revision: Union[str, None] = "20261021_0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paycor_payroll_journal_mapping_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("paycor_legal_entity_id", sa.Integer(), nullable=False),
        sa.Column("paycor_planner_id", sa.Text(), nullable=False),
        sa.Column("paycor_run_type", sa.Text(), nullable=True),
        sa.Column("maconomy_journal_number", sa.Text(), nullable=True),
        sa.Column("maconomy_instance_id", sa.Text(), nullable=True),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_paycor_payroll_journal_mapping_log"),
        ),
        sa.UniqueConstraint(
            "paycor_legal_entity_id",
            "paycor_planner_id",
            name="uq_paycor_payroll_mapping_legal_entity_planner",
        ),
    )
    op.create_table(
        "paycor_payroll_integration_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "paycor_payroll_journal_mapping_log_id",
            sa.Uuid(),
            nullable=True,
        ),
        sa.Column("paycor_planner_id", sa.Text(), nullable=True),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "SUCCESS",
                "FAILED",
                name="paycor_payroll_integration_status",
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "action",
            sa.Enum(
                "CREATE",
                "UPDATE",
                name="paycor_payroll_integration_action",
            ),
            nullable=False,
        ),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["paycor_payroll_journal_mapping_log_id"],
            ["paycor_payroll_journal_mapping_log.id"],
            name=op.f(
                "fk_paycor_payroll_integration_logs_"
                "paycor_payroll_journal_mapping_log_id_"
                "paycor_payroll_journal_mapping_log"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_paycor_payroll_integration_logs"),
        ),
    )


def downgrade() -> None:
    op.drop_table("paycor_payroll_integration_logs")
    op.drop_table("paycor_payroll_journal_mapping_log")
