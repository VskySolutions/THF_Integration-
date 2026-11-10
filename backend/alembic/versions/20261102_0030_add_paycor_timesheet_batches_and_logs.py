"""add paycor timesheet batches and logs

Revision ID: 20261102_0030
Revises: 20261021_0028
Create Date: 2026-11-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261102_0030"
down_revision: Union[str, None] = "20261027_0029"
branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None
depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


timesheet_submission_mode = postgresql.ENUM(
    "APPEND",
    "REPLACE",
    name="paycor_timesheet_submission_mode",
    create_type=False,
)

timesheet_submission_status = postgresql.ENUM(
    "SUBMITTING",
    "ACCEPTED",
    "FAILED",
    "UNKNOWN",
    name="paycor_timesheet_submission_status",
    create_type=False,
)


def upgrade() -> None:
    timesheet_submission_mode.create(
        op.get_bind(),
        checkfirst=True,
    )
    timesheet_submission_status.create(
        op.get_bind(),
        checkfirst=True,
    )

    op.create_table(
        "paycor_timesheet_batches",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "paycor_legal_entity_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "source_start_date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "source_end_date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "pay_group_id",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "pay_period_start",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "pay_period_end",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "accepted_process_id",
            sa.Uuid(),
            nullable=True,
        ),
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
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_paycor_timesheet_batches"),
        ),
        sa.UniqueConstraint(
            "paycor_legal_entity_id",
            "source_start_date",
            "source_end_date",
            "pay_group_id",
            "pay_period_start",
            "pay_period_end",
            name="uq_paycor_timesheet_batch_group",
        ),
    )

    op.create_table(
        "paycor_timesheet_integration_logs",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "timesheet_batch_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "process_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "submission_mode",
            timesheet_submission_mode,
            nullable=False,
        ),
        sa.Column(
            "status",
            timesheet_submission_status,
            nullable=False,
        ),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "http_status",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "response",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "completed_on_utc",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["timesheet_batch_id"],
            ["paycor_timesheet_batches.id"],
            name=op.f(
                "fk_paycor_timesheet_integration_logs_"
                "timesheet_batch_id_"
                "paycor_timesheet_batches"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f(
                "pk_paycor_timesheet_integration_logs"
            ),
        ),
    )

    op.create_index(
        "ix_paycor_timesheet_logs_batch_created",
        "paycor_timesheet_integration_logs",
        [
            "timesheet_batch_id",
            "created_on_utc",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_paycor_timesheet_logs_batch_created",
        table_name=(
            "paycor_timesheet_integration_logs"
        ),
    )
    op.drop_table(
        "paycor_timesheet_integration_logs"
    )
    op.drop_table("paycor_timesheet_batches")

    timesheet_submission_status.drop(
        op.get_bind(),
        checkfirst=True,
    )
    timesheet_submission_mode.drop(
        op.get_bind(),
        checkfirst=True,
    )
