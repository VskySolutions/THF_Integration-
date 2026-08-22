"""Add SKIPPED to the CaseWare integration status enum.

Revision ID: 20260822_0007
Revises: 1d6acee49b76
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260822_0007"
down_revision: Union[str, None] = "1d6acee49b76"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE caseware_integration_status "
        "ADD VALUE IF NOT EXISTS 'SKIPPED'"
    )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed without recreating the enum type.
    pass
