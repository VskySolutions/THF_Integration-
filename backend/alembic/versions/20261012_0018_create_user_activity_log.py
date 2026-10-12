"""Create user activity log table.

Revision ID: 20261012_0018
Revises: 20261012_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "20261012_0018"
down_revision: str | None = "20261012_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_activity_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("service", sa.Text(), nullable=True),
        sa.Column("data", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("user", sa.Text(), nullable=False),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_activity_log")),
    )
    op.create_index(
        "ix_user_activity_log_user",
        "user_activity_log",
        ["user"],
    )
    op.create_index(
        "ix_user_activity_log_created_on_utc",
        "user_activity_log",
        ["created_on_utc"],
    )


def downgrade() -> None:
    op.drop_table("user_activity_log")
