from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.features.sap_concur_invoice_integration_v2.constants import (
    IntegrationAction,
    IntegrationStatus,
)

if TYPE_CHECKING:
    from app.features.sap_concur_invoice_integration_v2.models.invoice_mapping import (
        SAPConcurInvoiceMappingV2,
    )


class SAPConcurInvoiceIntegrationLogV2(Base):
    """Stores v2 invoice and run outcomes."""

    __tablename__ = "sap_concur_invoice_integration_logs_v2"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sap_concur_invoice_mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sap_concur_invoice_mapping_v2.id"), nullable=True
    )
    instance: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[IntegrationStatus] = mapped_column(
        ENUM(
            IntegrationStatus,
            name="sap_concur_invoice_integration_status_v2",
            create_type=False,
        ),
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_stage: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment=(
            "Processing stages are INVOICE_FETCH, INVOICE_CREATION, "
            "LINE_CREATION, SUBMISSION, APPROVAL, and COMPLETED."
        ),
    )
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    action: Mapped[IntegrationAction] = mapped_column(
        ENUM(
            IntegrationAction,
            name="sap_concur_invoice_integration_action_v2",
            create_type=False,
        ),
        nullable=False,
    )
    invoice_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    invoice_mapping: Mapped[SAPConcurInvoiceMappingV2 | None] = relationship(
        back_populates="integration_logs"
    )
