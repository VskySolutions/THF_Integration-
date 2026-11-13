from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.features.sap_concur_invoice_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)

if TYPE_CHECKING:
    from app.features.sap_concur_invoice_integration.models.invoice_mapping import (
        SAPConcurInvoiceMapping,
    )


class SAPConcurInvoiceIntegrationLog(Base):
    """Database log for SAP Concur invoice -> Maconomy sync operations.

    Analog of ``sap_concur_integration_logs`` (expense feature) with the
    invoice-flow deviations documented in WO[#27.9]: no employeeemail
    (no data source), Maconomy ids live on the mapping only, invoice_id
    carries the "N/A" sentinel for run-level logs (reference convention).
    """

    __tablename__ = "sap_concur_invoice_integration_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Nullable: set for per-invoice logs of SUCCESS rows; NULL for
    # run-level logs (fetch/journal/summary) and FAILED-row invoices.
    sap_concur_invoice_mapping_id: Mapped[uuid.UUID | None] = (
        mapped_column(
            ForeignKey("sap_concur_invoice_mapping.id"), nullable=True
        )
    )
    instance: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[IntegrationStatus] = mapped_column(
        Enum(IntegrationStatus, name="sap_concur_invoice_integration_status"),
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nullable Text (NOT a PG enum) — no second enum type; values defined
    # by ProcessingStage in constants.py (INVOICE_FETCH /
    # JOURNAL_CREATION / INVOICE_ALLOCATION_LINE_CREATION / COMPLETED).
    processing_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured snapshot (free-form dict by repo convention — no
    # Pydantic contract; mirrors the expense log's details column):
    # run summary = the exact FR-9 response; abort logs =
    # {"stage", "error"}; per-invoice logs = {"row", "lines", "line_error"}.
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    action: Mapped[IntegrationAction] = mapped_column(
        Enum(IntegrationAction, name="sap_concur_invoice_integration_action"),
        nullable=False,
    )
    # SAP Concur invoice id; "N/A" sentinel for run-level logs
    # (reference: report_id="N/A").
    invoice_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    invoice_mapping: Mapped[SAPConcurInvoiceMapping | None] = relationship(
        back_populates="integration_logs"
    )
