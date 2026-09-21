import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.xcm_cch_axcess_integration.constants import (
    IntegrationRunStatus,
    IntegrationTriggerType,
)
from app.features.xcm_cch_axcess_integration.models import (
    XCMCCHIntegrationRunLog,
)


async def start_run(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    maconomy_instance: str,
    trigger_type: IntegrationTriggerType = IntegrationTriggerType.API,
) -> XCMCCHIntegrationRunLog | None:
    run_log = XCMCCHIntegrationRunLog(
        request_id=request_id,
        trigger_type=trigger_type.value,
        status=IntegrationRunStatus.RUNNING.value,
        maconomy_instance=maconomy_instance,
    )
    try:
        session.add(run_log)
        await session.commit()
        await session.refresh(run_log)
    except Exception:
        await session.rollback()
        return None
    return run_log


async def complete_run_from_jobs(
    session: AsyncSession,
    run_log: XCMCCHIntegrationRunLog | None,
    jobs: list[dict[str, Any]],
) -> bool:
    if run_log is None:
        return False

    linked = 0
    created = 0
    updated = 0
    manual_review = 0
    failed_jobs: list[dict[str, Any]] = []
    manual_review_jobs: list[dict[str, Any]] = []

    for job in jobs:
        job_number = _string_value(job.get("jobnumber"))
        resolution = job.get("cchtaskresolution")
        resolution_status = (
            resolution.get("status") if isinstance(resolution, dict) else None
        )
        writeback_status = job.get("maconomywritebackstatus")

        if resolution_status == "existing":
            linked += 1
        elif resolution_status == "created":
            created += 1
        elif resolution_status == "manual_review":
            manual_review += 1
            manual_review_jobs.append(
                {
                    "job_number": job_number,
                    "match_count": resolution.get("matchcount"),
                }
            )

        if writeback_status == "updated":
            updated += 1

        if resolution_status == "failed":
            failed_jobs.append(
                {
                    "job_number": job_number,
                    "stage": "CCH_TASK_RESOLUTION",
                    "reason": _string_value(resolution.get("error")),
                }
            )
        elif writeback_status == "failed":
            failed_jobs.append(
                {
                    "job_number": job_number,
                    "stage": "MACONOMY_WRITEBACK",
                    "reason": _string_value(job.get("maconomywritebackerror")),
                }
            )

    failed_count = len(failed_jobs)
    if failed_count == 0 and manual_review == 0:
        run_status = IntegrationRunStatus.SUCCESS
        failure_stage = None
        error_message = None
    elif jobs and failed_count == len(jobs):
        run_status = IntegrationRunStatus.FAILED
        failure_stage = "JOB_PROCESSING"
        error_message = "All discovered jobs failed"
    else:
        run_status = IntegrationRunStatus.PARTIAL_SUCCESS
        failure_stage = (
            "JOB_PROCESSING" if failed_count else "MANUAL_REVIEW"
        )
        error_message = "Some jobs failed or require manual review"

    run_log.status = run_status.value
    run_log.completed_on_utc = datetime.now(timezone.utc)
    run_log.jobs_discovered = len(jobs)
    run_log.tasks_linked = linked
    run_log.tasks_created = created
    run_log.jobs_updated = updated
    run_log.manual_review_count = manual_review
    run_log.failed_count = failed_count
    run_log.failure_stage = failure_stage
    run_log.error_message = error_message
    run_log.details = {
        "failed_jobs": failed_jobs,
        "manual_review_jobs": manual_review_jobs,
    }
    return await _commit(session)


async def fail_run(
    session: AsyncSession,
    run_log: XCMCCHIntegrationRunLog | None,
    *,
    failure_stage: str,
    error_message: str,
    jobs_discovered: int = 0,
) -> bool:
    if run_log is None:
        return False

    run_log.status = IntegrationRunStatus.FAILED.value
    run_log.completed_on_utc = datetime.now(timezone.utc)
    run_log.jobs_discovered = jobs_discovered
    run_log.failed_count = jobs_discovered
    run_log.failure_stage = failure_stage
    run_log.error_message = error_message
    run_log.details = None
    return await _commit(session)


async def _commit(session: AsyncSession) -> bool:
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        return False
    return True


def _string_value(value: Any) -> str | None:
    return str(value) if value is not None else None
