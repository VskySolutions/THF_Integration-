from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
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
    from app.features.paycor_integration.models.timesheet_integration_log import (
        PaycorTimesheetIntegrationLog,
    )


class PaycorTimesheetBatch(Base):
    __tablename__ = "paycor_timesheet_batches"

    __table_args__ = (
        UniqueConstraint(
            "paycor_legal_entity_id",
            "pay_group_id",
            "pay_period_start",
            "pay_period_end",
            name="uq_paycor_timesheet_batch_group",
        ),
        UniqueConstraint(
            "process_id",
            name="uq_paycor_timesheet_batches_process_id",
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

    source_start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    source_end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    pay_group_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    pay_period_start: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    pay_period_end: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    process_id: Mapped[uuid.UUID] = mapped_column(
        default=uuid.uuid4,
        nullable=False,
    )

    accepted_process_id: Mapped[
        uuid.UUID | None
    ] = mapped_column(
        nullable=True,
    )

    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_on_utc: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=func.now(),
    )

    submission_logs: Mapped[
        list[PaycorTimesheetIntegrationLog]
    ] = relationship(
        back_populates="timesheet_batch",
    )
