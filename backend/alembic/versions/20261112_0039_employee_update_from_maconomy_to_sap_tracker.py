"""Employee update from maconomy to SAP tracker and sync logging.

Revision ID: 20261112_0039
Revises: 20261111_0038
Create Date: 2026-11-12 18:50:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261112_0039"
down_revision: Union[str, None] = "20261111_0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Main Tracking Table (Current State)
    op.create_table(
        "employee_sync_tracking",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "maconomy_employee_number",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "sap_concur_user_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "maconomy_version",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "sync_status",
            sa.String(length=20),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "maconomy_employee_number",
            name="uq_employee_sync_tracking_maconomy_employee_number",
        ),
    )

    op.create_index(
        "ix_employee_sync_tracking_maconomy_emp_num",
        "employee_sync_tracking",
        ["maconomy_employee_number"],
        unique=False,
    )
    op.create_index(
        "ix_employee_sync_tracking_sap_concur_user_id",
        "employee_sync_tracking",
        ["sap_concur_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_employee_sync_tracking_sync_status",
        "employee_sync_tracking",
        ["sync_status"],
        unique=False,
    )

    # 2. Sync Execution & Error Logging Table (Historical Audit Trail)
    op.create_table(
        "employee_sync_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "tracking_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_sync_tracking.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "maconomy_employee_number",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "sap_concur_user_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "action",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "old_version",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "new_version",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_employee_sync_log_tracking_id",
        "employee_sync_log",
        ["tracking_id"],
        unique=False,
    )
    op.create_index(
        "ix_employee_sync_log_maconomy_emp_num",
        "employee_sync_log",
        ["maconomy_employee_number"],
        unique=False,
    )
    op.create_index(
        "ix_employee_sync_log_status",
        "employee_sync_log",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_employee_sync_log_action",
        "employee_sync_log",
        ["action"],
        unique=False,
    )
    op.create_index(
        "ix_employee_sync_log_created_at",
        "employee_sync_log",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_employee_sync_log_created_at", table_name="employee_sync_log")
    op.drop_index("ix_employee_sync_log_action", table_name="employee_sync_log")
    op.drop_index("ix_employee_sync_log_status", table_name="employee_sync_log")
    op.drop_index("ix_employee_sync_log_maconomy_emp_num", table_name="employee_sync_log")
    op.drop_index("ix_employee_sync_log_tracking_id", table_name="employee_sync_log")
    op.drop_table("employee_sync_log")

    op.drop_index(
        "ix_employee_sync_tracking_sync_status",
        table_name="employee_sync_tracking",
    )
    op.drop_index(
        "ix_employee_sync_tracking_sap_concur_user_id",
        table_name="employee_sync_tracking",
    )
    op.drop_index(
        "ix_employee_sync_tracking_maconomy_emp_num",
        table_name="employee_sync_tracking",
    )
    op.drop_table("employee_sync_tracking")
