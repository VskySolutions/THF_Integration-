"""Create integration service master table and seed service switches.

Revision ID: 20260831_0008
Revises: a8c4bafd2f52
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260831_0008"
down_revision: str | None = "20260810_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    integration_service = op.create_table(
        "integration_service",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identifier_unique_name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("source_system", sa.Text(), nullable=True),
        sa.Column("target_system", sa.Text(), nullable=True),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_service")),
        sa.UniqueConstraint(
            "identifier_unique_name",
            name=op.f("uq_integration_service_identifier_unique_name"),
        ),
    )

def downgrade() -> None:
    op.drop_table("integration_service")
