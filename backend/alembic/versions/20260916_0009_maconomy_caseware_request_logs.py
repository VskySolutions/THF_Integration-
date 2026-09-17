"""Add status tracking for the Maconomy-owned CaseWare integration.

Revision ID: 20260916_0009
Revises: 20260831_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260916_0009"
down_revision: str | None = "20260831_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "maconomy_caseware_cloud_request_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("maconomy_instance", sa.Text(), nullable=False),
        sa.Column("job_number", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_on_utc", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maconomy_caseware_cloud_request_logs")),
    )
    op.create_index(
        op.f("ix_maconomy_caseware_cloud_request_logs_request_id"),
        "maconomy_caseware_cloud_request_logs", ["request_id"],
    )
    op.create_index(
        op.f("ix_maconomy_caseware_cloud_request_logs_job_number"),
        "maconomy_caseware_cloud_request_logs", ["job_number"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_maconomy_caseware_cloud_request_logs_job_number"),
        table_name="maconomy_caseware_cloud_request_logs",
    )
    op.drop_index(
        op.f("ix_maconomy_caseware_cloud_request_logs_request_id"),
        table_name="maconomy_caseware_cloud_request_logs",
    )
    op.drop_table("maconomy_caseware_cloud_request_logs")
