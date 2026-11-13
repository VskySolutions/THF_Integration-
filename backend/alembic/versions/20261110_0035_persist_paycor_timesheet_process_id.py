"""Persist an idempotent process ID for each Paycor timesheet batch.

Revision ID: 20261110_0035
Revises: 20261110_0034
Create Date: 2026-11-10
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261110_0035"
down_revision: str | None = "20261110_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paycor_timesheet_batches",
        sa.Column(
            "process_id",
            sa.Uuid(),
            nullable=True,
        ),
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE paycor_timesheet_batches AS batch
            SET process_id = COALESCE(
                batch.accepted_process_id,
                (
                    SELECT accepted.process_id
                    FROM paycor_timesheet_integration_logs AS accepted
                    WHERE
                        accepted.timesheet_batch_id = batch.id
                        AND accepted.status = 'ACCEPTED'
                    ORDER BY
                        accepted.created_on_utc DESC,
                        accepted.id DESC
                    LIMIT 1
                ),
                (
                    SELECT submission.process_id
                    FROM paycor_timesheet_integration_logs AS submission
                    WHERE submission.timesheet_batch_id = batch.id
                    ORDER BY
                        submission.created_on_utc ASC,
                        submission.id ASC
                    LIMIT 1
                )
            )
            """
        )
    )

    batch_table = sa.table(
        "paycor_timesheet_batches",
        sa.column("id", sa.Uuid()),
        sa.column("process_id", sa.Uuid()),
    )
    missing_batch_ids = connection.execute(
        sa.select(batch_table.c.id).where(
            batch_table.c.process_id.is_(None)
        )
    ).scalars()

    for batch_id in missing_batch_ids:
        connection.execute(
            batch_table.update()
            .where(batch_table.c.id == batch_id)
            .values(process_id=uuid.uuid4())
        )

    duplicate_groups = connection.execute(
        sa.text(
            """
            SELECT
                paycor_legal_entity_id,
                pay_group_id,
                pay_period_start,
                pay_period_end
            FROM paycor_timesheet_batches
            GROUP BY
                paycor_legal_entity_id,
                pay_group_id,
                pay_period_start,
                pay_period_end
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()

    if duplicate_groups is not None:
        raise RuntimeError(
            "Duplicate Paycor timesheet batches exist for the same "
            "legal entity, pay group, and pay period. Reconcile their "
            "process IDs before applying revision 20261110_0035."
        )

    op.alter_column(
        "paycor_timesheet_batches",
        "process_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_paycor_timesheet_batches_process_id",
        "paycor_timesheet_batches",
        ["process_id"],
    )
    op.drop_constraint(
        "uq_paycor_timesheet_batch_group",
        "paycor_timesheet_batches",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_paycor_timesheet_batch_group",
        "paycor_timesheet_batches",
        [
            "paycor_legal_entity_id",
            "pay_group_id",
            "pay_period_start",
            "pay_period_end",
        ],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_paycor_timesheet_batch_group",
        "paycor_timesheet_batches",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_paycor_timesheet_batch_group",
        "paycor_timesheet_batches",
        [
            "paycor_legal_entity_id",
            "source_start_date",
            "source_end_date",
            "pay_group_id",
            "pay_period_start",
            "pay_period_end",
        ],
    )
    op.drop_constraint(
        "uq_paycor_timesheet_batches_process_id",
        "paycor_timesheet_batches",
        type_="unique",
    )
    op.drop_column(
        "paycor_timesheet_batches",
        "process_id",
    )
