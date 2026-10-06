"""Seed the THF monitoring system administrator account.

Revision ID: 20261006_0016
Revises: 20261006_0015
"""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "20261006_0016"
down_revision: str | None = "20261006_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

THF_SYSADMIN_ID = "5c91be1a-da9d-44eb-9236-cd0a9e03393f"
THF_SYSADMIN_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$7YCVgzK6eCssG3nSiaKQNg"
    "$2ed/mdSC5Xm2oyA/YDNInBPVwBFWFSOvB76GdEhx21k"
)


def upgrade() -> None:
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("username", sa.String()),
        sa.column("email_id", sa.String()),
        sa.column("password_hash", sa.String()),
        sa.column("is_deleted", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        users,
        [
            {
                "id": THF_SYSADMIN_ID,
                "username": "ThfSysAdmin",
                "email_id": "thfsysadmin@thf.local",
                "password_hash": THF_SYSADMIN_PASSWORD_HASH,
                "is_deleted": False,
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
    )
    op.execute(
        users.delete().where(
            users.c.id == uuid.UUID(THF_SYSADMIN_ID)
        )
    )
