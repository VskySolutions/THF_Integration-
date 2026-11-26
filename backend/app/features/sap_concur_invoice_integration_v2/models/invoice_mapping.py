from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.features.sap_concur_invoice_integration_v2.constants import InvoiceActionStatus

if TYPE_CHECKING:
    from app.features.sap_concur_invoice_integration_v2.models.integration_log import (
        SAPConcurInvoiceIntegrationLogV2,
    )


_invoice_action_status = ENUM(
    InvoiceActionStatus,
    name="sap_concur_invoice_action_status_v2",
    create_type=False,
)


class SAPConcurInvoiceMappingV2(Base):
    """Links a Concur invoice to the identifiers returned by Maconomy."""

    __tablename__ = "sap_concur_invoice_mapping_v2"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    journalnumber: Mapped[str] = mapped_column(Text, nullable=False)
    maconomy_invoice_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sap_concur_invoice_id: Mapped[str] = mapped_column(Text, nullable=False)
    allocation_lines_status: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=dict
    )
    is_submitted: Mapped[InvoiceActionStatus] = mapped_column(
        _invoice_action_status, nullable=False, server_default="SKIPPED"
    )
    is_approved: Mapped[InvoiceActionStatus] = mapped_column(
        _invoice_action_status, nullable=False, server_default="SKIPPED"
    )
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    integration_logs: Mapped[list[SAPConcurInvoiceIntegrationLogV2]] = relationship(
        back_populates="invoice_mapping"
    )
