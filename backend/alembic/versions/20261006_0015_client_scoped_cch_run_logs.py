"""Add client-scoped CCH integration run logs.

Revision ID: 20261006_0015
Revises: 20261005_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261006_0015"
down_revision: str | None = "20261005_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "xcm_cch_client_scoped_run_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("maconomy_instance", sa.Text(), nullable=False),
        sa.Column(
            "started_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "jobs_discovered", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "jobs_succeeded", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "clients_created", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("tasks_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("summary_message", sa.Text(), nullable=False),
        sa.Column("failure_stage", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_xcm_cch_client_scoped_run_logs")
        ),
    )
    op.create_index(
        op.f("ix_xcm_cch_client_scoped_run_logs_request_id"),
        "xcm_cch_client_scoped_run_logs",
        ["request_id"],
    )
    op.create_index(
        op.f("ix_xcm_cch_client_scoped_run_logs_status"),
        "xcm_cch_client_scoped_run_logs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_xcm_cch_client_scoped_run_logs_status"),
        table_name="xcm_cch_client_scoped_run_logs",
    )
    op.drop_index(
        op.f("ix_xcm_cch_client_scoped_run_logs_request_id"),
        table_name="xcm_cch_client_scoped_run_logs",
    )
    op.drop_table("xcm_cch_client_scoped_run_logs")
