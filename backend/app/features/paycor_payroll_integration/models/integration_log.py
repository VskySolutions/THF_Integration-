from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Text,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db.base import Base
from app.features.paycor_payroll_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)

if TYPE_CHECKING:
    from app.features.paycor_payroll_integration.models.payroll_journal_mapping_log import (
        PaycorPayrollJournalMappingLog,
    )


class PaycorPayrollIntegrationLog(Base):
    """Database audit log for individual Paycor to Maconomy sync operations."""

    __tablename__ = "paycor_payroll_integration_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    paycor_payroll_journal_mapping_log_id: Mapped[
        uuid.UUID | None
    ] = mapped_column(
        ForeignKey(
            "paycor_payroll_journal_mapping_log.id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )

    paycor_planner_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    department: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    instance: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    base_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[IntegrationStatus] = mapped_column(
        Enum(
            IntegrationStatus,
            name="paycor_payroll_integration_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )

    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    action: Mapped[IntegrationAction] = mapped_column(
        Enum(
            IntegrationAction,
            name="paycor_payroll_integration_action",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )

    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    journal_mapping_log: Mapped[
        PaycorPayrollJournalMappingLog | None
    ] = relationship(
        back_populates="integration_logs",
    )

