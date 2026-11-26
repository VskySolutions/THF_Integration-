"""Store submission and approval outcomes on V2 invoice mappings."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "20261124_0050"
down_revision: str | None = "20261121_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MAPPING_TABLE = "sap_concur_invoice_mapping_v2"
_LOG_TABLE = "sap_concur_invoice_integration_logs_v2"
_ACTION_STATUS = postgresql.ENUM(
    "SKIPPED",
    "FAILED",
    "SUCCESS",
    name="sap_concur_invoice_action_status_v2",
    create_type=False,
)
_OLD_STAGE_COMMENT = (
    "Processing stages are INVOICE_FETCH, INVOICE_CREATION, "
    "LINE_CREATION, SUBMISSION, and COMPLETED."
)
_NEW_STAGE_COMMENT = (
    "Processing stages are INVOICE_FETCH, INVOICE_CREATION, "
    "LINE_CREATION, SUBMISSION, APPROVAL, and COMPLETED."
)


def upgrade() -> None:
    _ACTION_STATUS.create(op.get_bind(), checkfirst=False)
    for column in ("is_submitted", "is_approved"):
        op.add_column(
            _MAPPING_TABLE,
            sa.Column(column, _ACTION_STATUS, nullable=False, server_default="SKIPPED"),
        )
    op.alter_column(_LOG_TABLE, "processing_stage", comment=_NEW_STAGE_COMMENT)


def downgrade() -> None:
    op.alter_column(_LOG_TABLE, "processing_stage", comment=_OLD_STAGE_COMMENT)
    op.drop_column(_MAPPING_TABLE, "is_approved")
    op.drop_column(_MAPPING_TABLE, "is_submitted")
    _ACTION_STATUS.drop(op.get_bind(), checkfirst=False)
