"""Create and seed Paycor timesheet schedules.

Revision ID: 20261118_0047
Revises: 20261112_0043
Create Date: 2026-11-18
"""

import uuid
from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "20261118_0047"
down_revision: str | None = "20261112_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEDULE_ROWS = (
    ("2027-01-11", "2026-12-21", "2027-01-03"),
    ("2027-01-25", "2027-01-04", "2027-01-17"),
    ("2027-02-08", "2027-01-18", "2027-01-31"),
    ("2027-02-22", "2027-02-01", "2027-02-14"),
    ("2027-03-09", "2027-02-15", "2027-02-28"),
    ("2027-03-27", "2027-03-01", "2027-03-21"),
    ("2027-04-11", "2027-03-22", "2027-04-04"),
    ("2027-04-26", "2027-04-05", "2027-04-18"),
    ("2027-05-10", "2027-04-19", "2027-05-02"),
    ("2027-05-24", "2027-05-03", "2027-05-16"),
    ("2027-06-09", "2027-05-17", "2027-05-30"),
    ("2027-06-26", "2027-05-31", "2027-06-20"),
    ("2027-07-11", "2027-06-21", "2027-07-04"),
    ("2027-07-26", "2027-07-05", "2027-07-18"),
    ("2027-08-09", "2027-07-19", "2027-08-01"),
    ("2027-08-25", "2027-08-02", "2027-08-15"),
    ("2027-09-11", "2027-08-16", "2027-09-05"),
    ("2027-09-26", "2027-09-06", "2027-09-19"),
    ("2027-10-11", "2027-09-20", "2027-10-03"),
    ("2027-10-25", "2027-10-04", "2027-10-17"),
    ("2027-11-08", "2027-10-18", "2027-10-31"),
    ("2027-11-22", "2027-11-01", "2027-11-14"),
    ("2027-12-11", "2027-11-15", "2027-12-05"),
    ("2027-12-27", "2027-12-06", "2027-12-19"),
)


def upgrade() -> None:
    schedule_status = postgresql.ENUM(
        "PENDING",
        "PROCESSING",
        "COMPLETED",
        "FAILED",
        "MISSED",
        name="paycor_timesheet_schedule_status",
        create_type=False,
    )
    schedule_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "paycor_timesheet_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "import_from_maconomy_date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column("workweek_start", sa.Date(), nullable=False),
        sa.Column("workweek_end", sa.Date(), nullable=False),
        sa.Column(
            "status",
            schedule_status,
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "started_on_utc",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_on_utc",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_on_utc",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "workweek_end >= workweek_start",
            name="ck_paycor_timesheet_schedules_"
            "paycor_timesheet_schedule_date_range",
        ),
        sa.CheckConstraint(
            "EXTRACT(ISODOW FROM workweek_start) = 1",
            name="ck_paycor_timesheet_schedules_"
            "paycor_timesheet_schedule_start_monday",
        ),
        sa.CheckConstraint(
            "EXTRACT(ISODOW FROM workweek_end) = 7",
            name="ck_paycor_timesheet_schedules_"
            "paycor_timesheet_schedule_end_sunday",
        ),
        sa.CheckConstraint(
            "import_from_maconomy_date > workweek_end",
            name="ck_paycor_timesheet_schedules_"
            "paycor_timesheet_schedule_import_after_workweeks",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_paycor_timesheet_schedules",
        ),
        sa.UniqueConstraint(
            "import_from_maconomy_date",
            "workweek_start",
            "workweek_end",
            name="uq_paycor_timesheet_schedule_import_range",
        ),
    )

    schedule_table = sa.table(
        "paycor_timesheet_schedules",
        sa.column("id", sa.Uuid()),
        sa.column("import_from_maconomy_date", sa.Date()),
        sa.column("workweek_start", sa.Date()),
        sa.column("workweek_end", sa.Date()),
        sa.column("status", schedule_status),
        sa.column("attempt_count", sa.Integer()),
    )
    namespace = uuid.UUID("9f4b96b2-1b31-4ab9-a098-47e18b20b391")
    op.bulk_insert(
        schedule_table,
        [
            {
                "id": uuid.uuid5(
                    namespace,
                    "|".join(row),
                ),
                "import_from_maconomy_date": date.fromisoformat(row[0]),
                "workweek_start": date.fromisoformat(row[1]),
                "workweek_end": date.fromisoformat(row[2]),
                "status": "PENDING",
                "attempt_count": 0,
            }
            for row in SCHEDULE_ROWS
        ],
    )


def downgrade() -> None:
    op.drop_table("paycor_timesheet_schedules")
    postgresql.ENUM(
        name="paycor_timesheet_schedule_status"
    ).drop(op.get_bind(), checkfirst=True)
