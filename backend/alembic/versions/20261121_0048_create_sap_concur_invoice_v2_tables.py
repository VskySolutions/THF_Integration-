"""Create the SAP Concur invoice v2 mapping and log tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "20261121_0048"
down_revision: str | None = "20261118_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status_type = postgresql.ENUM(
        "SUCCESS",
        "FAILED",
        "SKIPPED",
        "PARTIALLY_SUCCESS",
        name="sap_concur_invoice_integration_status",
        create_type=False,
    )
    action_type = postgresql.ENUM(
        "CREATE",
        "UPDATE",
        "RETRY_CREATE",
        name="sap_concur_invoice_integration_action",
        create_type=False,
    )

    op.create_table(
        "sap_concur_invoice_mapping_v2",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("journalnumber", sa.Text(), nullable=False),
        sa.Column("maconomy_invoice_number", sa.Integer(), nullable=True),
        sa.Column("sap_concur_invoice_id", sa.Text(), nullable=False),
        sa.Column("allocation_lines_status", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sap_concur_invoice_mapping_v2")),
    )

    op.create_table(
        "sap_concur_invoice_integration_logs_v2",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sap_concur_invoice_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("status", status_type, nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "processing_stage",
            sa.Text(),
            nullable=True,
            comment=(
                "Processing stages are INVOICE_FETCH, INVOICE_CREATION, "
                "LINE_CREATION, SUBMISSION, and COMPLETED."
            ),
        ),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("action", action_type, nullable=False),
        sa.Column("invoice_id", sa.Text(), nullable=False),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["sap_concur_invoice_mapping_id"],
            ["sap_concur_invoice_mapping_v2.id"],
            name=op.f(
                "fk_sap_concur_invoice_integration_logs_v2_"
                "sap_concur_invoice_mapping_id_sap_concur_invoice_mapping_v2"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_sap_concur_invoice_integration_logs_v2")
        ),
    )


def downgrade() -> None:
    op.drop_table("sap_concur_invoice_integration_logs_v2")
    op.drop_table("sap_concur_invoice_mapping_v2")
