import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.paycor_integration.constants import (
    TimesheetScheduleStatus,
)
from app.features.paycor_integration.models.timesheet_schedule import (
    PaycorTimesheetSchedule,
)


class TimesheetScheduleError(ValueError):
    pass


class TimesheetScheduleNotFoundError(TimesheetScheduleError):
    pass


class TimesheetScheduleNotDueError(TimesheetScheduleError):
    pass


async def list_pending_schedules(
    session: AsyncSession,
    *,
    from_date: date,
) -> list[PaycorTimesheetSchedule]:
    statement = (
        select(PaycorTimesheetSchedule)
        .where(
            PaycorTimesheetSchedule.status
            == TimesheetScheduleStatus.PENDING,
            PaycorTimesheetSchedule.import_from_maconomy_date
            >= from_date,
        )
        .order_by(
            PaycorTimesheetSchedule.import_from_maconomy_date,
            PaycorTimesheetSchedule.workweek_start,
        )
    )
    result = await session.scalars(statement)
    return list(result.all())


async def claim_due_schedule(
    session: AsyncSession,
    *,
    schedule_id: uuid.UUID,
    current_eastern_date: date,
) -> PaycorTimesheetSchedule:
    statement = (
        select(PaycorTimesheetSchedule)
        .where(PaycorTimesheetSchedule.id == schedule_id)
        .with_for_update()
    )
    schedule = await session.scalar(statement)

    if schedule is None:
        await session.rollback()
        raise TimesheetScheduleNotFoundError(
            "Paycor timesheet schedule was not found"
        )

    if (
        schedule.status != TimesheetScheduleStatus.PENDING
        or schedule.import_from_maconomy_date
        != current_eastern_date
    ):
        await session.rollback()
        raise TimesheetScheduleNotDueError(
            "Paycor timesheet schedule is not pending for today"
        )

    schedule.status = TimesheetScheduleStatus.PROCESSING
    schedule.attempt_count += 1
    schedule.started_on_utc = datetime.now(timezone.utc)
    schedule.completed_on_utc = None
    schedule.last_error = None
    await session.commit()
    await session.refresh(schedule)
    return schedule


async def mark_schedule_completed(
    session: AsyncSession,
    *,
    schedule_id: uuid.UUID,
) -> None:
    schedule = await session.get(
        PaycorTimesheetSchedule,
        schedule_id,
    )
    if schedule is None:
        raise TimesheetScheduleNotFoundError(
            "Paycor timesheet schedule was not found"
        )
    schedule.status = TimesheetScheduleStatus.COMPLETED
    schedule.completed_on_utc = datetime.now(timezone.utc)
    schedule.last_error = None
    await session.commit()


async def mark_schedule_failed(
    session: AsyncSession,
    *,
    schedule_id: uuid.UUID,
    error: str,
) -> None:
    schedule = await session.get(
        PaycorTimesheetSchedule,
        schedule_id,
    )
    if schedule is None:
        raise TimesheetScheduleNotFoundError(
            "Paycor timesheet schedule was not found"
        )
    schedule.status = TimesheetScheduleStatus.FAILED
    schedule.completed_on_utc = datetime.now(timezone.utc)
    schedule.last_error = error[:4000]
    await session.commit()
