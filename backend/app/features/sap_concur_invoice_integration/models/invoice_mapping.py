from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.features.sap_concur_invoice_integration.models.integration_log import (
        SAPConcurInvoiceIntegrationLog,
    )


class SAPConcurInvoiceMapping(Base):
    """SAP Concur invoice -> Maconomy journal/invoice-row linkage.

    Analog of ``sap_concur_expensesheet_expensereport_mapping`` (expense
    feature) with the user-corrected column set (WO[#27.9], 2026-11-11):
    no submit/approve/row-status columns — the mapping is created only
    when the Maconomy invoice row was created (reference-strict).
    """

    __tablename__ = "sap_concur_invoice_mapping"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Maconomy-side ids: the run's journal number + this invoice row's
    # line number within it (the Q-1 linkage fields).
    journalnumber: Mapped[str] = mapped_column(Text, nullable=False)
    journallinenumber: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # SAP Concur invoice id (PaymentRequestId / ID).
    sap_concur_invoice_id: Mapped[str] = mapped_column(Text, nullable=False)
    # {<sap_concur_line_id>: <maconomy_line_number>} (user 2026-11-11):
    # key = Concur line id, value = the created Maconomy allocation line
    # number (null when the line FAILED / not extractable); {} when no
    # lines were created. Free-form dict by repo convention (mirrors the
    # expense feature's expense_line_metadata JSONB).
    allocation_lines_status: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=dict
    )
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    integration_logs: Mapped[list[SAPConcurInvoiceIntegrationLog]] = relationship(
        back_populates="invoice_mapping"
    )
