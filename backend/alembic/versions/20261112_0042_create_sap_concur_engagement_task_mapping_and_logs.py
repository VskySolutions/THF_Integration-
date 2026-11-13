"""create sap concur engagement task mapping and logs

Revision ID: 20261112_0038
Revises: 20261112_0037
Create Date: 2026-11-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261112_0042"
down_revision: Union[str, None] = "20261112_0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


engagement_task_integration_status = postgresql.ENUM(
    "SUCCESS",
    "FAILED",
    "SKIPPED",
    name="sap_concur_engagement_task_integration_status",
    create_type=False,
)

engagement_task_integration_action = postgresql.ENUM(
    "CREATE",
    "UPDATE",
    "RETRY_CREATE",
    name="sap_concur_engagement_task_integration_action",
    create_type=False,
)


def upgrade() -> None:
    engagement_task_integration_status.create(op.get_bind(), checkfirst=True)
    engagement_task_integration_action.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "sap_concur_engagement_task_mapping",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("maconomy_jobnumber", sa.Text(), nullable=False),
        sa.Column("maconomy_tasknumber", sa.Text(), nullable=False),
        sa.Column("sap_concur_engagement_id", sa.Text(), nullable=True),
        sa.Column("sap_concur_task_id", sa.Text(), nullable=True),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_sap_concur_engagement_task_mapping")
        ),
        sa.UniqueConstraint(
            "maconomy_jobnumber",
            "maconomy_tasknumber",
            name=op.f(
                "uq_sap_concur_engagement_task_mapping_maconomy_jobnumber"
            ),
        ),
    )

    op.create_table(
        "sap_concur_engagement_task_integration_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "sap_concur_engagement_task_mapping_id",
            sa.Uuid(),
            nullable=True,
        ),
        sa.Column("maconomy_jobnumber", sa.Text(), nullable=False),
        sa.Column("maconomy_tasknumber", sa.Text(), nullable=False),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column(
            "status", engagement_task_integration_status, nullable=False
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("action", engagement_task_integration_action, nullable=False),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["sap_concur_engagement_task_mapping_id"],
            ["sap_concur_engagement_task_mapping.id"],
            name=op.f(
                "fk_sap_concur_engagement_task_integration_logs_"
                "sap_concur_engagement_task_mapping_id_"
                "sap_concur_engagement_task_mapping"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_sap_concur_engagement_task_integration_logs")
        ),
    )


def downgrade() -> None:
    op.drop_table("sap_concur_engagement_task_integration_logs")
    op.drop_table("sap_concur_engagement_task_mapping")
    engagement_task_integration_action.drop(op.get_bind(), checkfirst=True)
    engagement_task_integration_status.drop(op.get_bind(), checkfirst=True)
