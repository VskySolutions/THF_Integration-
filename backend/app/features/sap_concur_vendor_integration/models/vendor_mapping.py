from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.features.sap_concur_vendor_integration.models.integration_log import (
        SAPConcurVendorIntegrationLog,
    )


class SAPConcurVendorMapping(Base):
    __tablename__ = "sap_concur_vendor_mapping"
    __table_args__ = (
        UniqueConstraint(
            "sap_concur_vendor_code",
            name="uq_sap_concur_vendor_mapping_sap_concur_vendor_code",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sap_concur_vendor_code: Mapped[str] = mapped_column(Text, nullable=False)
    maconomy_vendor_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    integration_logs: Mapped[list[SAPConcurVendorIntegrationLog]] = (
        relationship(back_populates="vendor_mapping")
    )
