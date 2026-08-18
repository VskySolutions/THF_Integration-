"""change_cw_addresses_to_jsonb

Revision ID: cd312664b17e
Revises: 20260814_0006
Create Date: 2026-08-18 15:16:00.469728
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'cd312664b17e'
down_revision: Union[str, None] = '20260814_0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column(
        "caseware_cloud_entity_engagement_mapping",
        "cw_addresses",
    )

    op.add_column(
        "caseware_cloud_entity_engagement_mapping",
        sa.Column(
            "cw_addresses",
            postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "caseware_cloud_entity_engagement_mapping",
        "cw_addresses",
    )

    op.add_column(
        "caseware_cloud_entity_engagement_mapping",
        sa.Column(
            "cw_addresses",
            postgresql.ARRAY(sa.INTEGER()),
            nullable=True,
        ),
    )