from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.features.sap_concur_integration.models.integration_log import (
        SAPConcurIntegrationLog,
    )


class SAPConcurExpensesheetExpenseReportMapping(Base):
    __tablename__ = "sap_concur_expensesheet_expensereport_mapping"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    maconomy_expensesheet_no: Mapped[str] = mapped_column(Text, nullable=False)
    sap_concur_expensereport_id: Mapped[str] = mapped_column(Text, nullable=False)

    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    integration_logs: Mapped[list[SAPConcurIntegrationLog]] = relationship(
        back_populates="expensesheet_expensereport_mapping"
    )
