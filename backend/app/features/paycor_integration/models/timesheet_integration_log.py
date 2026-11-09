from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Text,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db.base import Base
from app.features.paycor_integration.constants import (
    TimesheetSubmissionMode,
    TimesheetSubmissionStatus,
)


if TYPE_CHECKING:
    from app.features.paycor_integration.models.timesheet_batch import (
        PaycorTimesheetBatch,
    )


class PaycorTimesheetIntegrationLog(Base):
    __tablename__ = "paycor_timesheet_integration_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    timesheet_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paycor_timesheet_batches.id"),
        nullable=False,
    )

    process_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
    )

    submission_mode: Mapped[
        TimesheetSubmissionMode
    ] = mapped_column(
        Enum(
            TimesheetSubmissionMode,
            name="paycor_timesheet_submission_mode",
        ),
        nullable=False,
    )

    status: Mapped[
        TimesheetSubmissionStatus
    ] = mapped_column(
        Enum(
            TimesheetSubmissionStatus,
            name="paycor_timesheet_submission_status",
        ),
        nullable=False,
    )

    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )

    http_status: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    response: Mapped[Any | None] = mapped_column(
        JSON,
        nullable=True,
    )

    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    completed_on_utc: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    timesheet_batch: Mapped[
        PaycorTimesheetBatch
    ] = relationship(
        back_populates="submission_logs",
    )
