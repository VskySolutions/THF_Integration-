"""Retry workflow for Maconomy engagement/tasks -> SAP Concur creation.

Single-engagement retry: fetches the job from Maconomy by jobnumber (the
batch's two-day ``createddate`` window is deliberately NOT applied so
older engagements stay reachable), fetches the job's approved tasks,
pre-checks the (jobnumber, tasknumber) pairs against the mapping table,
and bulk-creates only the unmapped items in SAP Concur. Exactly per-item
``action=RETRY_CREATE`` integration-log rows are written (SKIPPED for
each excluded mapped pair, SUCCESS/FAILED for each sent engagement/task)
via a non-fatal logging wrapper. Engagement rows use the
``tasknumber=""`` sentinel, same as the batch.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.sap_concur_engagements_and_tasks_integration.mappers.engagement_mapper import (
    build_engagements_payload,
)
from app.features.sap_concur_engagements_and_tasks_integration.mappers.sap_concur_mapper import (
    build_bulk_list_payload,
)
from app.features.sap_concur_engagements_and_tasks_integration.models.integration_log import (
    EngagementTaskIntegrationAction,
    EngagementTaskIntegrationStatus,
)
from app.features.sap_concur_engagements_and_tasks_integration.services import (
    engagement_task_mapping_service,
    integration_log_service,
)
from app.features.sap_concur_engagements_and_tasks_integration.services.maconomy_services import (
    MaconomyService,
    MaconomyServiceError,
)
from app.features.sap_concur_engagements_and_tasks_integration.services.sap_concur_service import (
    SAPConcurEngagementTaskService,
    SAPConcurEngagementTaskServiceError,
)

_RETRY_TIMEOUT_SECONDS = 60.0

_SUCCESS_STATUS = "SUCCESS"
_PARTIAL_STATUS = "PARTIAL_SUCCESS"


async def _safe_retry_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    maconomy_jobnumber: str,
    maconomy_tasknumber: str,
    status_value: EngagementTaskIntegrationStatus,
    message: str,
) -> None:
    """Non-fatal wrapper: a logging failure must never mask the outcome."""
    try:
        await integration_log_service.create_log(
            session,
            mapping_id=mapping_id,
            maconomy_jobnumber=maconomy_jobnumber,
            maconomy_tasknumber=maconomy_tasknumber,
            status=status_value,
            action=EngagementTaskIntegrationAction.RETRY_CREATE,
            message=message,
        )
    except Exception:
        pass


async def _safe_create_mapping(
    session: AsyncSession,
    *,
    maconomy_jobnumber: str,
    maconomy_tasknumber: str,
) -> uuid.UUID | None:
    """Persist one mapping row; a mapping failure never breaks the run.

    Callers only pass pairs proven absent from ``get_existing_pairs``, so
    the unique constraint on (jobnumber, tasknumber) is respected.
    """
    try:
        mapping = await engagement_task_mapping_service.create_mapping(
            session,
            maconomy_jobnumber=maconomy_jobnumber,
            maconomy_tasknumber=maconomy_tasknumber,
        )
        return mapping.id
    except Exception:
        return None


def _failure_reason(error: dict[str, Any]) -> str:
    parts = [
        part
        for part in (
            str(error.get("id") or "").strip(),
            str(error.get("message") or "").strip(),
        )
        if part
    ]
    return ": ".join(parts) or "creation failed"


def _result_counts(
    *,
    engagements_sent: int,
    tasks_sent: int,
    engagements_created: int,
    tasks_created: int,
    skipped_pairs: int,
    concur_status: str | None,
) -> dict[str, Any]:
    return {
        "engagements_sent": engagements_sent,
        "tasks_sent": tasks_sent,
        "engagements_created": engagements_created,
        "tasks_created": tasks_created,
        "skipped_pairs": skipped_pairs,
        "concur_status": concur_status,
    }


async def retry_engagement_task_sync(
    session: AsyncSession,
    *,
    engagement_no: str,
) -> dict[str, Any]:
    """Retry one Maconomy engagement (and its unmapped tasks) into Concur.

    Returns a structured dict with ``engagement_no``, ``status``
    (SUCCESS/SKIPPED/PARTIAL_SUCCESS/FAILED), ``message`` and ``result``
    counts. Raises 400 for a blank code, 404 when Maconomy has no such
    open job or no approved tasks, and 502 on Maconomy connectivity
    failures (each already logged with ``action=RETRY_CREATE`` before
    raising). Create outcomes always return HTTP 200 with a structured
    status (matches the vendor retry split).
    """
    normalized_code = engagement_no.strip()
    if not normalized_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="engagement_no is required",
        )

    try:
        return await _run_retry_engagement_task_sync(
            session, engagement_no=normalized_code
        )
    except HTTPException:
        raise
    except Exception as exc:
        await _safe_retry_log(
            session,
            mapping_id=None,
            maconomy_jobnumber=normalized_code,
            maconomy_tasknumber="",
            status_value=EngagementTaskIntegrationStatus.FAILED,
            message=f"Retry processing failed: {str(exc)[:1000]}",
        )
        raise


async def _run_retry_engagement_task_sync(
    session: AsyncSession,
    *,
    engagement_no: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_RETRY_TIMEOUT_SECONDS) as client:
        maconomy_service = MaconomyService(client)
        try:
            await maconomy_service.authenticate()
        except MaconomyServiceError as exc:
            await _safe_retry_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=engagement_no,
                maconomy_tasknumber="",
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=(
                    "Failed to authenticate with Maconomy: "
                    f"{str(exc)[:1000]}"
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to authenticate with Maconomy",
            ) from exc
        try:
            job = await maconomy_service.get_engagement_by_jobnumber(
                engagement_no
            )
        except MaconomyServiceError as exc:
            await _safe_retry_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=engagement_no,
                maconomy_tasknumber="",
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=(
                    "Failed to fetch engagement from Maconomy: "
                    f"{str(exc)[:1000]}"
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve engagement from Maconomy",
            ) from exc

        if job is None:
            await _safe_retry_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=engagement_no,
                maconomy_tasknumber="",
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=(
                    f"Engagement {engagement_no} not found in Maconomy"
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Engagement {engagement_no} not found in Maconomy"
                ),
            )

        jobnumber = str(job.get("jobnumber") or "").strip() or engagement_no
        tasklist = str(job.get("tasklist") or "").strip()

        try:
            tasks = (
                await maconomy_service.get_tasks_by_task_lists([tasklist])
                if tasklist
                else []
            )
        except MaconomyServiceError as exc:
            await _safe_retry_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=jobnumber,
                maconomy_tasknumber="",
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=(
                    "Failed to fetch tasks from Maconomy: "
                    f"{str(exc)[:1000]}"
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve tasks from Maconomy",
            ) from exc

    if not tasks:
        await _safe_retry_log(
            session,
            mapping_id=None,
            maconomy_jobnumber=jobnumber,
            maconomy_tasknumber="",
            status_value=EngagementTaskIntegrationStatus.FAILED,
            message=(
                f"No approved tasks found for engagement {jobnumber}"
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No approved tasks found for engagement {jobnumber}"
            ),
        )

    engagement = build_engagements_payload([job], tasks)["engagements"][0]

    existing_pairs = await engagement_task_mapping_service.get_existing_pairs(
        session, [jobnumber]
    )

    engagement_synced = (jobnumber, "") in existing_pairs
    skipped_pairs: list[tuple[str, str]] = []
    selected_tasks: list[dict[str, str]] = []
    sent_tasks: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for task in engagement.get("tasks") or []:
        tasknumber = str(task.get("task_no") or "").strip()
        if not tasknumber:
            continue
        pair = (jobnumber, tasknumber)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        if pair in existing_pairs:
            skipped_pairs.append(pair)
            continue
        selected_tasks.append(task)
        sent_tasks.append(pair)

    sent_engagements: list[str] = []
    if engagement_synced:
        skipped_pairs.insert(0, (jobnumber, ""))
    else:
        sent_engagements.append(jobnumber)

    for skipped_jobnumber, skipped_tasknumber in skipped_pairs:
        if skipped_tasknumber:
            message = (
                f"Task {skipped_tasknumber} ({skipped_jobnumber}) "
                "already synced - skipped"
            )
        else:
            message = (
                f"Engagement {skipped_jobnumber} already synced - skipped"
            )
        await _safe_retry_log(
            session,
            mapping_id=None,
            maconomy_jobnumber=skipped_jobnumber,
            maconomy_tasknumber=skipped_tasknumber,
            status_value=EngagementTaskIntegrationStatus.SKIPPED,
            message=message,
        )

    if not sent_engagements and not sent_tasks:
        return {
            "engagement_no": jobnumber,
            "status": "SKIPPED",
            "message": "Engagement and all tasks already synced - skipped",
            "result": _result_counts(
                engagements_sent=0,
                tasks_sent=0,
                engagements_created=0,
                tasks_created=0,
                skipped_pairs=len(skipped_pairs),
                concur_status=None,
            ),
        }

    selected_engagements = [
        {
            "engagement_no": jobnumber,
            "engagement_name": str(engagement.get("engagement_name") or ""),
            "tasks": selected_tasks,
            "include_entry": not engagement_synced,
        }
    ]

    bulk_payload = build_bulk_list_payload(selected_engagements)
    try:
        result = await SAPConcurEngagementTaskService().create_engagements_and_tasks(
            bulk_payload
        )
    except SAPConcurEngagementTaskServiceError as exc:
        for failed_jobnumber in sent_engagements:
            await _safe_retry_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=failed_jobnumber,
                maconomy_tasknumber="",
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=(
                    f"Engagement {failed_jobnumber} creation failed: {exc}"
                ),
            )
        for failed_jobnumber, failed_tasknumber in sent_tasks:
            await _safe_retry_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=failed_jobnumber,
                maconomy_tasknumber=failed_tasknumber,
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=(
                    f"Task {failed_tasknumber} ({failed_jobnumber}) "
                    f"creation failed: {exc}"
                ),
            )
        return {
            "engagement_no": jobnumber,
            "status": "FAILED",
            "message": str(exc),
            "result": _result_counts(
                engagements_sent=len(sent_engagements),
                tasks_sent=len(sent_tasks),
                engagements_created=0,
                tasks_created=0,
                skipped_pairs=len(skipped_pairs),
                concur_status=None,
            ),
        }

    concur_status = str(result.get("status") or "")
    failure_reasons: dict[tuple[str, ...], str] = {}
    if concur_status == _PARTIAL_STATUS:
        for error in result.get("errors") or []:
            if not isinstance(error, dict):
                continue
            list_item = error.get("listItem")
            if not isinstance(list_item, dict):
                continue
            short_code = str(list_item.get("shortCode") or "").strip()
            parent_code = str(list_item.get("parentCode") or "").strip()
            if not short_code:
                continue
            reason = _failure_reason(error)
            if parent_code:
                failure_reasons[("task", parent_code, short_code)] = reason
            else:
                failure_reasons[("eng", short_code)] = reason

    failed_whole_run = concur_status not in (_SUCCESS_STATUS, _PARTIAL_STATUS)

    created_engagements = 0
    for sent_jobnumber in sent_engagements:
        key: tuple[str, ...] = ("eng", sent_jobnumber)
        if failed_whole_run or key in failure_reasons:
            reason = failure_reasons.get(key) or (
                f"bulk request status {concur_status or 'UNKNOWN'}"
            )
            await _safe_retry_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=sent_jobnumber,
                maconomy_tasknumber="",
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=(
                    f"Engagement {sent_jobnumber} creation failed: {reason}"
                ),
            )
            continue
        mapping_id = await _safe_create_mapping(
            session,
            maconomy_jobnumber=sent_jobnumber,
            maconomy_tasknumber="",
        )
        await _safe_retry_log(
            session,
            mapping_id=mapping_id,
            maconomy_jobnumber=sent_jobnumber,
            maconomy_tasknumber="",
            status_value=EngagementTaskIntegrationStatus.SUCCESS,
            message=f"Engagement {sent_jobnumber} created in SAP Concur",
        )
        created_engagements += 1

    created_tasks = 0
    for sent_jobnumber, sent_tasknumber in sent_tasks:
        key = ("task", sent_jobnumber, sent_tasknumber)
        if failed_whole_run or key in failure_reasons:
            reason = failure_reasons.get(key) or (
                f"bulk request status {concur_status or 'UNKNOWN'}"
            )
            await _safe_retry_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=sent_jobnumber,
                maconomy_tasknumber=sent_tasknumber,
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=(
                    f"Task {sent_tasknumber} ({sent_jobnumber}) "
                    f"creation failed: {reason}"
                ),
            )
            continue
        mapping_id = await _safe_create_mapping(
            session,
            maconomy_jobnumber=sent_jobnumber,
            maconomy_tasknumber=sent_tasknumber,
        )
        await _safe_retry_log(
            session,
            mapping_id=mapping_id,
            maconomy_jobnumber=sent_jobnumber,
            maconomy_tasknumber=sent_tasknumber,
            status_value=EngagementTaskIntegrationStatus.SUCCESS,
            message=(
                f"Task {sent_tasknumber} ({sent_jobnumber}) "
                "created in SAP Concur"
            ),
        )
        created_tasks += 1

    total_sent = len(sent_engagements) + len(sent_tasks)
    total_created = created_engagements + created_tasks
    if failed_whole_run:
        overall_status = "FAILED"
        message = (
            f"Engagement {jobnumber} creation failed: "
            f"bulk request status {concur_status or 'UNKNOWN'}"
        )
    elif total_created == total_sent:
        overall_status = "SUCCESS"
        message = f"Engagement {jobnumber} created in SAP Concur"
        if created_tasks:
            message += f" with {created_tasks} task(s)"
    else:
        overall_status = "PARTIAL_SUCCESS"
        message = (
            f"Engagement {jobnumber} partially created in SAP Concur "
            f"({total_created} of {total_sent} items)"
        )

    return {
        "engagement_no": jobnumber,
        "status": overall_status,
        "message": message,
        "result": _result_counts(
            engagements_sent=len(sent_engagements),
            tasks_sent=len(sent_tasks),
            engagements_created=created_engagements,
            tasks_created=created_tasks,
            skipped_pairs=len(skipped_pairs),
            concur_status=concur_status or None,
        ),
    }
