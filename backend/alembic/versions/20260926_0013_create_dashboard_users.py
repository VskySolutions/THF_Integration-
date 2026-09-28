"""Create dashboard users and seed the default SysAdmin account."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_0013"
down_revision: str | None = "3563461727f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSADMIN_ID = "6ad0bf04-3ba2-4fa8-888a-e7ac4e9b8461"
SYSADMIN_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$93RK8t0Kux+czaPI6jwmgA"
    "$7OhKBiSuSB+m5xYgUwD0MowLEo5Q5eg/qodeFkryQb8"
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("email_id", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email_id"), "users", ["email_id"], unique=True)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

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
                "id": SYSADMIN_ID,
                "username": "SysAdmin",
                "email_id": "sysadmin@falcon.local",
                "password_hash": SYSADMIN_PASSWORD_HASH,
                "is_deleted": False,
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_email_id"), table_name="users")
    op.drop_table("users")
