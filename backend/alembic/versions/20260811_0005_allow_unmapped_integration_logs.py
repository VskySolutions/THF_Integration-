"""Allow integration logs before an engagement mapping exists."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260811_0005"
down_revision: str | None = "20260810_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "caseware_cloud_integration_logs",
        "caseware_cloud_entity_engagement_mapping_id",
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "caseware_cloud_integration_logs",
        "caseware_cloud_entity_engagement_mapping_id",
        nullable=False,
    )
