"""Add HubSpot integration run logs.

Revision ID: 20261018_0025
Revises: 20261014_0024

This migration is setup only. It must be executed manually by the user.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "20261018_0025"
down_revision: str | None = "20261014_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hubspot_integration_run_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
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
            "customers_discovered",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "customers_succeeded",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "contacts_discovered",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "contacts_succeeded",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "associations_succeeded",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "checkpoints_succeeded",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "skipped_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "failed_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("summary_message", sa.Text(), nullable=False),
        sa.Column("failure_stage", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_hubspot_integration_run_logs"),
        ),
    )
    op.create_index(
        op.f("ix_hubspot_integration_run_logs_request_id"),
        "hubspot_integration_run_logs",
        ["request_id"],
    )
    op.create_index(
        op.f("ix_hubspot_integration_run_logs_operation"),
        "hubspot_integration_run_logs",
        ["operation"],
    )
    op.create_index(
        op.f("ix_hubspot_integration_run_logs_status"),
        "hubspot_integration_run_logs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_hubspot_integration_run_logs_status"),
        table_name="hubspot_integration_run_logs",
    )
    op.drop_index(
        op.f("ix_hubspot_integration_run_logs_operation"),
        table_name="hubspot_integration_run_logs",
    )
    op.drop_index(
        op.f("ix_hubspot_integration_run_logs_request_id"),
        table_name="hubspot_integration_run_logs",
    )
    op.drop_table("hubspot_integration_run_logs")
