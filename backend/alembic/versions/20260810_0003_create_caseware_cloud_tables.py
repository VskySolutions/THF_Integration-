"""Create Caseware Cloud mapping and integration log tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260810_0003"
down_revision: str | None = "20260810_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

status_enum = postgresql.ENUM("SUCCESS", "FAILED", name="caseware_integration_status")
action_enum = postgresql.ENUM("CREATE", "UPDATE", name="caseware_integration_action")


def upgrade() -> None:
    bind = op.get_bind()
    status_enum.create(bind, checkfirst=True)
    action_enum.create(bind, checkfirst=True)

    op.create_table(
        "caseware_cloud_entity_engagement_mapping",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("caseware_cloud_entity_cwid", sa.Text(), nullable=False),
        sa.Column("mapitonomy_job_number", sa.Text(), nullable=False),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_caseware_cloud_entity_engagement_mapping")
        ),
    )

    op.create_table(
        "caseware_cloud_integration_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "caseware_cloud_entity_engagement_mapping_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "SUCCESS",
                "FAILED",
                name="caseware_integration_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "action",
            postgresql.ENUM(
                "CREATE",
                "UPDATE",
                name="caseware_integration_action",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("jobnumber", sa.Text(), nullable=False),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["caseware_cloud_entity_engagement_mapping_id"],
            ["caseware_cloud_entity_engagement_mapping.id"],
            name=op.f(
                "fk_caseware_cloud_integration_logs_"
                "caseware_cloud_entity_engagement_mapping_id_"
                "caseware_cloud_entity_engagement_mapping"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_caseware_cloud_integration_logs")),
    )


def downgrade() -> None:
    op.drop_table("caseware_cloud_integration_logs")
    op.drop_table("caseware_cloud_entity_engagement_mapping")
    action_enum.drop(op.get_bind(), checkfirst=True)
    status_enum.drop(op.get_bind(), checkfirst=True)
