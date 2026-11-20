import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.features.paycor_integration.constants import (
    TimesheetScheduleStatus,
)


class PaycorTimesheetSchedule(Base):
    __tablename__ = "paycor_timesheet_schedules"
    __table_args__ = (
        CheckConstraint(
            "workweek_end >= workweek_start",
            name="paycor_timesheet_schedule_date_range",
        ),
        CheckConstraint(
            "EXTRACT(ISODOW FROM workweek_start) = 1",
            name="paycor_timesheet_schedule_start_monday",
        ),
        CheckConstraint(
            "EXTRACT(ISODOW FROM workweek_end) = 7",
            name="paycor_timesheet_schedule_end_sunday",
        ),
        CheckConstraint(
            "import_from_maconomy_date > workweek_end",
            name="paycor_timesheet_schedule_import_after_workweeks",
        ),
        UniqueConstraint(
            "import_from_maconomy_date",
            "workweek_start",
            "workweek_end",
            name="uq_paycor_timesheet_schedule_import_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    import_from_maconomy_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    workweek_start: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    workweek_end: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    status: Mapped[TimesheetScheduleStatus] = mapped_column(
        Enum(
            TimesheetScheduleStatus,
            name="paycor_timesheet_schedule_status",
        ),
        nullable=False,
        default=TimesheetScheduleStatus.PENDING,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    started_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=func.now(),
    )
