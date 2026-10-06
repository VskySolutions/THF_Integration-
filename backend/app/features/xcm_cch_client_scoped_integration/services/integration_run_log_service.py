import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.xcm_cch_client_scoped_integration.models import (
    XCMCCHClientScopedRunLog,
)


async def start_run(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    maconomy_instance: str,
    trigger_type: str,
) -> XCMCCHClientScopedRunLog | None:
    run_log = XCMCCHClientScopedRunLog(
        request_id=request_id,
        trigger_type=trigger_type,
        status="RUNNING",
        maconomy_instance=maconomy_instance,
        summary_message="Integration run is in progress",
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
    run_log: XCMCCHClientScopedRunLog | None,
    *,
    discovered_job_numbers: list[str],
    jobs: list[dict[str, Any]],
) -> bool:
    if run_log is None:
        return False

    successful_job_numbers: list[str] = []
    failed_jobs: list[dict[str, Any]] = []
    job_results: list[dict[str, Any]] = []
    clients_created = 0
    tasks_created = 0
    jobs_updated = 0

    for job in jobs:
        job_number = _string_value(job.get("jobnumber")) or "UNKNOWN"
        client = _stage(job.get("cchclientcreation"))
        task = _stage(job.get("cchtaskcreation"))
        writeback_status = _string_value(job.get("maconomywritebackstatus"))
        writeback_error = _string_value(job.get("maconomywritebackerror"))

        succeeded_stages: list[str] = []
        if client["status"] == "created":
            clients_created += 1
            succeeded_stages.append("CCH_CLIENT_CREATION")
        if task["status"] == "created":
            tasks_created += 1
            succeeded_stages.append("CCH_TASK_CREATION")
        written_fields: list[str] = []
        if writeback_status == "updated":
            jobs_updated += 1
            written_fields.append("date5")
            if task["status"] == "created":
                written_fields.append("text20")
            succeeded_stages.append(
                f"MACONOMY_WRITEBACK({','.join(written_fields)})"
            )

        failure_stage, reason = _job_failure(
            client=client,
            task=task,
            writeback_status=writeback_status,
            writeback_error=writeback_error,
        )
        stage_details = {
            "client_creation": client,
            "task_creation": task,
            "maconomy_writeback": {
                "status": writeback_status,
                "written_fields": written_fields,
                "error": writeback_error,
            },
        }
        if failure_stage is None:
            successful_job_numbers.append(job_number)
            job_status = "SUCCESS"
        else:
            job_status = "PARTIAL_SUCCESS" if succeeded_stages else "FAILED"
            failed_jobs.append(
                {
                    "job_number": job_number,
                    "status": job_status,
                    "failed_stage": failure_stage,
                    "reason": reason,
                    "succeeded_stages": succeeded_stages,
                }
            )
        job_results.append(
            {
                "job_number": job_number,
                "status": job_status,
                "stages": stage_details,
            }
        )

    succeeded_count = len(successful_job_numbers)
    failed_count = len(failed_jobs)
    if failed_count == 0:
        status = "SUCCESS"
    elif succeeded_count or any(item["succeeded_stages"] for item in failed_jobs):
        status = "PARTIAL_SUCCESS"
    else:
        status = "FAILED"

    summary = _summary(discovered_job_numbers, successful_job_numbers, failed_jobs)
    run_log.status = status
    run_log.completed_on_utc = datetime.now(timezone.utc)
    run_log.jobs_discovered = len(discovered_job_numbers)
    run_log.jobs_succeeded = succeeded_count
    run_log.failed_count = failed_count
    run_log.clients_created = clients_created
    run_log.tasks_created = tasks_created
    run_log.jobs_updated = jobs_updated
    run_log.summary_message = summary
    run_log.failure_stage = "JOB_PROCESSING" if failed_count else None
    run_log.error_message = (
        "One or more jobs failed or partially failed" if failed_count else None
    )
    run_log.details = {
        "discovered_job_numbers": discovered_job_numbers,
        "successful_job_numbers": successful_job_numbers,
        "failed_jobs": failed_jobs,
        "job_results": job_results,
    }
    return await _commit(session)


async def fail_run(
    session: AsyncSession,
    run_log: XCMCCHClientScopedRunLog | None,
    *,
    failure_stage: str,
    error_message: str,
    discovered_job_numbers: list[str] | None = None,
) -> bool:
    if run_log is None:
        return False

    job_numbers = discovered_job_numbers or []
    failed_jobs = [
        {
            "job_number": job_number,
            "status": "FAILED",
            "failed_stage": failure_stage,
            "reason": error_message,
            "succeeded_stages": [],
        }
        for job_number in job_numbers
    ]
    run_log.status = "FAILED"
    run_log.completed_on_utc = datetime.now(timezone.utc)
    run_log.jobs_discovered = len(job_numbers)
    run_log.failed_count = len(job_numbers)
    run_log.summary_message = (
        _summary(job_numbers, [], failed_jobs)
        if job_numbers
        else f"Integration failed during {failure_stage}: {error_message}"
    )
    run_log.failure_stage = failure_stage
    run_log.error_message = error_message
    run_log.details = {
        "discovered_job_numbers": job_numbers,
        "successful_job_numbers": [],
        "failed_jobs": failed_jobs,
        "job_results": [],
    }
    return await _commit(session)


def _job_failure(
    *,
    client: dict[str, str | None],
    task: dict[str, str | None],
    writeback_status: str | None,
    writeback_error: str | None,
) -> tuple[str | None, str | None]:
    if client["status"] != "created":
        return "CCH_CLIENT_CREATION", client["error"] or "Client creation failed"
    if task["status"] != "created":
        return "CCH_TASK_CREATION", task["error"] or "Task creation failed"
    if writeback_status != "updated":
        return "MACONOMY_WRITEBACK", writeback_error or "Maconomy writeback failed"
    return None, None


def _stage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "status": None,
            "taskid": None,
            "error": "Stage result was not recorded",
        }
    return {
        "status": _string_value(value.get("status")),
        "taskid": value.get("taskid"),
        "error": _string_value(value.get("error")),
    }


def _summary(
    discovered: list[str],
    succeeded: list[str],
    failed: list[dict[str, Any]],
) -> str:
    success_text = ", ".join(succeeded) or "none"
    failure_text = "; ".join(
        f'{item["job_number"]}: {item["reason"]}' for item in failed
    ) or "none"
    return (
        f"{len(discovered)} jobs discovered to sync; "
        f"{len(succeeded)} succeeded [{success_text}]; "
        f"{len(failed)} failed [{failure_text}]"
    )


async def _commit(session: AsyncSession) -> bool:
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        return False
    return True


def _string_value(value: Any) -> str | None:
    return str(value) if value is not None else None
