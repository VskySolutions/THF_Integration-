"""rename mapitonomy_job_number to maconomy_job_number

Revision ID: 1d6acee49b76
Revises: b474bb1bb412
Create Date: 2026-08-19 15:23:03.433327
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "1d6acee49b76"
down_revision: Union[str, None] = "b474bb1bb412"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename mapitonomy_job_number to maconomy_job_number."""

    op.alter_column(
        "caseware_cloud_entity_engagement_mapping",
        "mapitonomy_job_number",
        new_column_name="maconomy_job_number",
    )


def downgrade() -> None:
    """Rename maconomy_job_number back to mapitonomy_job_number."""

    op.alter_column(
        "caseware_cloud_entity_engagement_mapping",
        "maconomy_job_number",
        new_column_name="mapitonomy_job_number",
    )