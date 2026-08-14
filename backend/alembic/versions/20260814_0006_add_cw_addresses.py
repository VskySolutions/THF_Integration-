"""Add Caseware address IDs to engagement mappings."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260814_0006"
down_revision: str | None = "20260811_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "caseware_cloud_entity_engagement_mapping",
        sa.Column("cw_addresses", postgresql.ARRAY(sa.Integer()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("caseware_cloud_entity_engagement_mapping", "cw_addresses")
