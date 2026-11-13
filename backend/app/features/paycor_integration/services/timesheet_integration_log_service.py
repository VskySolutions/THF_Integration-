"""Database operations for Paycor timesheet submission logs."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.paycor_integration.constants import (
    TimesheetSubmissionMode,
    TimesheetSubmissionStatus,
)
from app.features.paycor_integration.models.timesheet_integration_log import (
    PaycorTimesheetIntegrationLog,
)
from app.features.paycor_integration.models.timesheet_batch import (
    PaycorTimesheetBatch,
)


class TimesheetSubmissionBlockedError(ValueError):
    """Raised when a batch cannot start another submission."""


async def create_submitting_log(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID,
    process_id: uuid.UUID,
    submission_mode: TimesheetSubmissionMode,
    payload: dict[str, Any],
) -> PaycorTimesheetIntegrationLog:
    batch_statement = (
        select(PaycorTimesheetBatch)
        .where(
            PaycorTimesheetBatch.id == batch_id
        )
        .with_for_update()
    )
    batch = await session.scalar(batch_statement)

    if batch is None:
        await session.rollback()
        raise TimesheetSubmissionBlockedError(
            "Paycor timesheet batch was not found"
        )

    latest_log = await get_latest_log(
        session,
        batch_id=batch_id,
    )

    if (
        latest_log is not None
        and latest_log.status
        in {
            TimesheetSubmissionStatus.SUBMITTING,
            TimesheetSubmissionStatus.UNKNOWN,
        }
    ):
        await session.rollback()
        raise TimesheetSubmissionBlockedError(
            "Paycor timesheet batch requires "
            "manual reconciliation"
        )

    if (
        process_id != batch.process_id
    ):
        await session.rollback()
        raise TimesheetSubmissionBlockedError(
            "Paycor timesheet submissions must reuse "
            "the persisted batch process ID"
        )

    if (
        submission_mode
        == TimesheetSubmissionMode.APPEND
        and (
            latest_log is not None
            or batch.accepted_process_id is not None
        )
    ):
        await session.rollback()
        raise TimesheetSubmissionBlockedError(
            "An existing Paycor timesheet batch "
            "cannot be appended again"
        )

    integration_log = PaycorTimesheetIntegrationLog(
        timesheet_batch_id=batch_id,
        process_id=process_id,
        submission_mode=submission_mode,
        status=TimesheetSubmissionStatus.SUBMITTING,
        payload=payload,
    )
    session.add(integration_log)
    await session.commit()
    await session.refresh(integration_log)
    return integration_log


async def get_latest_log(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID,
) -> PaycorTimesheetIntegrationLog | None:
    statement = (
        select(PaycorTimesheetIntegrationLog)
        .where(
            PaycorTimesheetIntegrationLog.timesheet_batch_id
            == batch_id
        )
        .order_by(
            PaycorTimesheetIntegrationLog
            .created_on_utc.desc(),
            PaycorTimesheetIntegrationLog.id.desc(),
        )
        .limit(1)
    )

    return await session.scalar(statement)


async def get_latest_accepted_log(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID,
) -> PaycorTimesheetIntegrationLog | None:
    statement = (
        select(PaycorTimesheetIntegrationLog)
        .where(
            PaycorTimesheetIntegrationLog.timesheet_batch_id
            == batch_id,
            PaycorTimesheetIntegrationLog.status
            == TimesheetSubmissionStatus.ACCEPTED,
        )
        .order_by(
            PaycorTimesheetIntegrationLog
            .created_on_utc.desc(),
            PaycorTimesheetIntegrationLog.id.desc(),
        )
        .limit(1)
    )

    return await session.scalar(statement)


async def complete_log(
    session: AsyncSession,
    integration_log: PaycorTimesheetIntegrationLog,
    *,
    status: TimesheetSubmissionStatus,
    http_status: int | None,
    response: Any | None,
    message: str | None,
) -> PaycorTimesheetIntegrationLog:
    if status == TimesheetSubmissionStatus.SUBMITTING:
        raise ValueError(
            "A completed timesheet log cannot remain SUBMITTING"
        )

    integration_log.status = status
    integration_log.http_status = http_status
    integration_log.response = response
    integration_log.message = message
    integration_log.completed_on_utc = (
        datetime.now(timezone.utc)
    )

    await session.commit()
    await session.refresh(integration_log)
    return integration_log
