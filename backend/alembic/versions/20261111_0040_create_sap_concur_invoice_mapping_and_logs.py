"""create sap concur invoice mapping and logs

Revision ID: 20261111_0032
Revises: 20261102_0031
Create Date: 2026-11-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261111_0040"
down_revision: Union[str, None] = "20261112_0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


invoice_integration_status = postgresql.ENUM(
    "SUCCESS",
    "FAILED",
    "SKIPPED",
    "PARTIALLY_SUCCESS",
    name="sap_concur_invoice_integration_status",
    create_type=False,
)

invoice_integration_action = postgresql.ENUM(
    "CREATE",
    "UPDATE",
    "RETRY_CREATE",
    name="sap_concur_invoice_integration_action",
    create_type=False,
)


def upgrade() -> None:
    invoice_integration_status.create(op.get_bind(), checkfirst=True)
    invoice_integration_action.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "sap_concur_invoice_mapping",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("journalnumber", sa.Text(), nullable=False),
        sa.Column("journallinenumber", sa.Integer(), nullable=True),
        sa.Column("sap_concur_invoice_id", sa.Text(), nullable=False),
        sa.Column(
            "allocation_lines_status",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_on_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_sap_concur_invoice_mapping")
        ),
    )

    op.create_table(
        "sap_concur_invoice_integration_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sap_concur_invoice_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("status", invoice_integration_status, nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("processing_stage", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("action", invoice_integration_action, nullable=False),
        sa.Column("invoice_id", sa.Text(), nullable=False),
        sa.Column(
            "created_on_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["sap_concur_invoice_mapping_id"],
            ["sap_concur_invoice_mapping.id"],
            name=op.f(
                "fk_sap_concur_invoice_integration_logs_"
                "sap_concur_invoice_mapping_id_"
                "sap_concur_invoice_mapping"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_sap_concur_invoice_integration_logs")
        ),
    )


def downgrade() -> None:
    op.drop_table("sap_concur_invoice_integration_logs")
    op.drop_table("sap_concur_invoice_mapping")
    invoice_integration_action.drop(op.get_bind(), checkfirst=True)
    invoice_integration_status.drop(op.get_bind(), checkfirst=True)
