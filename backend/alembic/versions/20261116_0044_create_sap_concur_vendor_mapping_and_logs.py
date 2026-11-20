from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261116_0044"
down_revision: Union[str, None] = "20261112_0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


vendor_integration_status = postgresql.ENUM(
    "SUCCESS",
    "FAILED",
    "SKIPPED",
    name="sap_concur_vendor_integration_status",
    create_type=False,
)

vendor_integration_action = postgresql.ENUM(
    "CREATE",
    "UPDATE",
    "RETRY_CREATE",
    name="sap_concur_vendor_integration_action",
    create_type=False,
)


def upgrade() -> None:
    vendor_integration_status.create(op.get_bind(), checkfirst=True)
    vendor_integration_action.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "sap_concur_vendor_mapping",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sap_concur_vendor_code", sa.Text(), nullable=False),
        sa.Column("maconomy_vendor_code", sa.Text(), nullable=True),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_sap_concur_vendor_mapping")
        ),
        sa.UniqueConstraint(
            "sap_concur_vendor_code",
            name=op.f("uq_sap_concur_vendor_mapping_sap_concur_vendor_code"),
        ),
    )

    op.create_table(
        "sap_concur_vendor_integration_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "sap_concur_vendor_mapping_id",
            sa.Uuid(),
            nullable=True,
        ),
        sa.Column("sap_concur_vendor_code", sa.Text(), nullable=True),
        sa.Column("maconomy_vendor_code", sa.Text(), nullable=True),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("status", vendor_integration_status, nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("action", vendor_integration_action, nullable=False),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["sap_concur_vendor_mapping_id"],
            ["sap_concur_vendor_mapping.id"],
            name=op.f(
                "fk_sap_concur_vendor_integration_logs_"
                "sap_concur_vendor_mapping_id_"
                "sap_concur_vendor_mapping"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_sap_concur_vendor_integration_logs")
        ),
    )


def downgrade() -> None:
    op.drop_table("sap_concur_vendor_integration_logs")
    op.drop_table("sap_concur_vendor_mapping")
    vendor_integration_action.drop(op.get_bind(), checkfirst=True)
    vendor_integration_status.drop(op.get_bind(), checkfirst=True)
