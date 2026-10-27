from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db.base import Base

if TYPE_CHECKING:
    from app.features.paycor_payroll_integration.models.integration_log import (
        PaycorPayrollIntegrationLog,
    )


class PaycorPayrollJournalMappingLog(Base):
    __tablename__ = "paycor_payroll_journal_mapping_log"

    __table_args__ = (
        UniqueConstraint(
            "paycor_legal_entity_id",
            "paycor_planner_id",
            name="uq_paycor_payroll_mapping_legal_entity_planner",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    paycor_legal_entity_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    paycor_planner_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    paycor_run_type: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    maconomy_journal_number: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    maconomy_instance_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=func.now(),
    )

    integration_logs: Mapped[list[PaycorPayrollIntegrationLog]] = (
        relationship(
            back_populates="journal_mapping_log",
        )
    )
