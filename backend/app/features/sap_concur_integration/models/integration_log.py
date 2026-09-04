from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.features.sap_concur_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)

if TYPE_CHECKING:
    from app.features.sap_concur_integration.models.expensesheet_expensereport_mapping import (
        SAPConcurExpensesheetExpenseReportMapping,
    )


class SAPConcurIntegrationLog(Base):
    __tablename__ = "sap_concur_integration_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sap_concur_expensesheet_expensereport_mapping_id: Mapped[uuid.UUID | None] = (
        mapped_column(
            ForeignKey("sap_concur_expensesheet_expensereport_mapping.id"), nullable=True
        )
    )
    instance: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[IntegrationStatus] = mapped_column(
        Enum(IntegrationStatus, name="sap_concur_integration_status"), nullable=False
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[IntegrationAction] = mapped_column(
        Enum(IntegrationAction, name="sap_concur_integration_action"), nullable=False
    )
    # jobnumber: Mapped[str] = mapped_column(Text, nullable=False)
    # sap_concur_expensereport_id
    expensesheet_number: Mapped[str] = mapped_column(Text, nullable=False)
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    expensesheet_expensereport_mapping: Mapped[SAPConcurExpensesheetExpenseReportMapping | None] = (
        relationship(back_populates="integration_logs")
    )
