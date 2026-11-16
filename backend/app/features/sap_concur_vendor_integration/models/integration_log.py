from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.features.sap_concur_vendor_integration.models.vendor_mapping import (
        SAPConcurVendorMapping,
    )


class VendorIntegrationStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class VendorIntegrationAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    RETRY_CREATE = "RETRY_CREATE"


class SAPConcurVendorIntegrationLog(Base):
    __tablename__ = "sap_concur_vendor_integration_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sap_concur_vendor_mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sap_concur_vendor_mapping.id"), nullable=True
    )
    sap_concur_vendor_code: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    maconomy_vendor_code: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    instance: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[VendorIntegrationStatus] = mapped_column(
        Enum(
            VendorIntegrationStatus,
            name="sap_concur_vendor_integration_status",
        ),
        nullable=False,
    )
    action: Mapped[VendorIntegrationAction] = mapped_column(
        Enum(
            VendorIntegrationAction,
            name="sap_concur_vendor_integration_action",
        ),
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    vendor_mapping: Mapped[SAPConcurVendorMapping | None] = relationship(
        back_populates="integration_logs"
    )
