"""Create paycor payroll journal mapping and integration logs tables.

Revision ID: 20261027_0029
Revises: 20261021_0028
Create Date: 2026-10-27 00:00:00.000000

Supports 1-to-many department-segregated journals per Paycor payrun (planner).
Composite unique constraint: (paycor_legal_entity_id, paycor_planner_id, department).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261027_0029"
down_revision: Union[str, None] = "20261021_0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0. Defensive cleanup in case previous experimental runs left artifacts
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS paycor_payroll_integration_logs CASCADE;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS paycor_payroll_journal_mapping_log CASCADE;"))
    conn.execute(sa.text("DROP TYPE IF EXISTS paycor_payroll_integration_status CASCADE;"))
    conn.execute(sa.text("DROP TYPE IF EXISTS paycor_payroll_integration_action CASCADE;"))

    # 1. Create paycor_payroll_journal_mapping_log table
    op.create_table(
        "paycor_payroll_journal_mapping_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("paycor_legal_entity_id", sa.Integer(), nullable=False),
        sa.Column("paycor_planner_id", sa.Text(), nullable=False),
        sa.Column("department", sa.Text(), nullable=False),
        sa.Column("entity_code", sa.Text(), nullable=True),
        sa.Column("lines_count", sa.Integer(), nullable=True),
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
            "department",
            name="uq_paycor_payroll_mapping_entity_planner_department",
        ),
    )

    # 2. Create paycor_payroll_integration_logs table
    op.create_table(
        "paycor_payroll_integration_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "paycor_payroll_journal_mapping_log_id",
            sa.Uuid(),
            nullable=True,
        ),
        sa.Column("paycor_planner_id", sa.Text(), nullable=True),
        sa.Column("department", sa.Text(), nullable=True),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "SUCCESS",
                "FAILED",
                "SKIPPED",
                "PARTIAL_SUCCESS",
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
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_paycor_payroll_integration_logs"),
        ),
    )

    # 3. Register service in integration_service table so it appears in Falcon UI
    conn.execute(
        sa.text(
            """
            INSERT INTO integration_service (id, identifier_unique_name, display_name, is_active)
            VALUES (
                'c3d4e5f6-a7b8-9012-cdef-1234567890ab',
                'PAYCOR_PAYROLL_JOURNAL_SYNC',
                'Paycor Payroll to Maconomy General Journal Sync',
                true
            )
            ON CONFLICT (identifier_unique_name) DO NOTHING;
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM integration_service WHERE identifier_unique_name = 'PAYCOR_PAYROLL_JOURNAL_SYNC';"
        )
    )

    op.drop_table("paycor_payroll_integration_logs")
    op.drop_table("paycor_payroll_journal_mapping_log")

    bind = op.get_bind()
    sa.Enum(name="paycor_payroll_integration_action").drop(bind, checkfirst=True)
    sa.Enum(name="paycor_payroll_integration_status").drop(bind, checkfirst=True)
