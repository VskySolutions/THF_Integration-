"""Engagements & tasks sync endpoint.

Retrieves Maconomy engagements (jobs) and the tasks belonging to each
engagement's task list, pre-checks them against the mapping table
(already-synced pairs are excluded and logged SKIPPED), bulk-creates only
the selected items in SAP Concur, then persists mapping rows for
successful items and per-item integration logs for every outcome.

Flow: jobs/filter -> collect unique tasklists -> api_tasks/filter ->
build_engagements_payload -> pre-check vs mapping -> (nothing new ->
400) -> build_bulk_list_payload -> POST /list/v4/lists/{listid}/bulk ->
write mapping + integration logs. The Concur bulk response
(SUCCESS / PARTIAL_SUCCESS) is returned verbatim.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.integration_services.constants import IntegrationServiceIdentifier
from app.features.integration_services.dependencies.active_service import (
    require_active_integration_service,
)
from app.features.sap_concur_engagements_and_tasks_integration.constants import (
    DEFAULT_JOBS_LIMIT,
)
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


router = APIRouter(
    prefix="/sap-concur-engagements-and-tasks",
    tags=["sap-concur-engagements-and-tasks-integration"],
    dependencies=[
        Depends(require_api_key),
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier
                .MACONOMY_SAP_CONCUR_ENGAGEMENTS_AND_TASKS_SYNC
            )
        ),
    ],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]

_SUCCESS_STATUS = "SUCCESS"
_PARTIAL_STATUS = "PARTIAL_SUCCESS"


class SyncEngagementsAndTasksRequest(BaseModel):
    limit: int = Field(default=DEFAULT_JOBS_LIMIT, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


async def _safe_create_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    maconomy_jobnumber: str,
    maconomy_tasknumber: str,
    status_value: EngagementTaskIntegrationStatus,
    message: str,
) -> None:
    """Persist one integration log; a logging failure never breaks the run."""
    try:
        await integration_log_service.create_log(
            session,
            mapping_id=mapping_id,
            maconomy_jobnumber=maconomy_jobnumber,
            maconomy_tasknumber=maconomy_tasknumber,
            status=status_value,
            action=EngagementTaskIntegrationAction.CREATE,
            message=message,
        )
    except Exception as exc:
        # Safe logging (invoice/expense pattern): never mask the outcome.
        print(f"[engagement-task-log] failed to persist integration log: {exc}")


async def _safe_create_mapping(
    session: AsyncSession,
    *,
    maconomy_jobnumber: str,
    maconomy_tasknumber: str,
) -> uuid.UUID | None:
    """Persist one mapping row; a mapping failure never breaks the run."""
    try:
        mapping = await engagement_task_mapping_service.create_mapping(
            session,
            maconomy_jobnumber=maconomy_jobnumber,
            maconomy_tasknumber=maconomy_tasknumber,
        )
        return mapping.id
    except Exception as exc:
        print(
            f"[engagement-task-log] failed to persist mapping for "
            f"{maconomy_jobnumber}/{maconomy_tasknumber!r}: {exc}"
        )
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


@router.post(
    "/sync-engagements-and-tasks",
    response_model=dict[str, Any],
)
async def sync_engagements_and_tasks(
    session: DatabaseSession,
    payload: SyncEngagementsAndTasksRequest = SyncEngagementsAndTasksRequest(),
) -> dict[str, Any]:
    """Retrieve Maconomy engagements/tasks, sync the new ones, write DB."""
    # --- Step 1: Maconomy fetch (unchanged). ---
    async with httpx.AsyncClient(timeout=60.0) as client:
        service = MaconomyService(client)
        try:
            await service.authenticate()
            jobs = await service.get_engagements(
                limit=payload.limit,
                offset=payload.offset,
            )
            task_lists = sorted(
                {
                    tasklist
                    for tasklist in (
                        str(job.get("tasklist") or "").strip() for job in jobs
                    )
                    if tasklist
                }
            )
            tasks = (
                await service.get_tasks_by_task_lists(task_lists)
                if task_lists
                else []
            )
        except MaconomyServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve engagements and tasks from Maconomy",
            ) from exc

    engagements = build_engagements_payload(jobs, tasks)["engagements"]
    # return {"engagements": engagements, "count": len(engagements)}

    # --- Step 2: pre-check against the mapping table. Engagement pair is
    # (jobnumber, ""); task pair is (jobnumber, tasknumber). ---
    jobnumbers = sorted(
        {
            jobnumber
            for jobnumber in (
                str(engagement.get("engagement_no") or "").strip()
                for engagement in engagements
            )
            if jobnumber
        }
    )
    existing_pairs = await engagement_task_mapping_service.get_existing_pairs(
        session, jobnumbers
    )

    selected_engagements: list[dict[str, Any]] = []
    sent_engagements: list[str] = []
    sent_tasks: list[tuple[str, str]] = []
    skipped_pairs: list[tuple[str, str]] = []
    seen_engagements: set[str] = set()
    seen_tasks: set[tuple[str, str]] = set()
    seen_skipped: set[tuple[str, str]] = set()

    for engagement in engagements:
        jobnumber = str(engagement.get("engagement_no") or "").strip()
        if not jobnumber or jobnumber in seen_engagements:
            continue
        seen_engagements.add(jobnumber)

        engagement_synced = (jobnumber, "") in existing_pairs
        selected_tasks: list[dict[str, str]] = []
        for task in engagement.get("tasks") or []:
            tasknumber = str(task.get("task_no") or "").strip()
            if not tasknumber:
                continue
            pair = (jobnumber, tasknumber)
            if pair in existing_pairs:
                if pair not in seen_skipped:
                    seen_skipped.add(pair)
                    skipped_pairs.append(pair)
                continue
            if pair in seen_tasks:
                continue
            seen_tasks.add(pair)
            selected_tasks.append(task)
            sent_tasks.append(pair)

        if engagement_synced:
            if (jobnumber, "") not in seen_skipped:
                seen_skipped.add((jobnumber, ""))
                skipped_pairs.append((jobnumber, ""))
        else:
            sent_engagements.append(jobnumber)

        if engagement_synced and not selected_tasks:
            # Nothing new for this engagement (entry already logged skipped).
            continue

        selected_engagements.append(
            {
                "engagement_no": jobnumber,
                "engagement_name": str(engagement.get("engagement_name") or ""),
                "tasks": selected_tasks,
                # Parent already in Concur -> emit only its new tasks.
                "include_entry": not engagement_synced,
            }
        )

    # --- Step 3: per-item SKIPPED logs for every pre-check match. ---
    for jobnumber, tasknumber in skipped_pairs:
        if tasknumber:
            message = f"Task {tasknumber} ({jobnumber}) already synced - skipped"
        else:
            message = f"Engagement {jobnumber} already synced - skipped"
        await _safe_create_log(
            session,
            mapping_id=None,
            maconomy_jobnumber=jobnumber,
            maconomy_tasknumber=tasknumber,
            status_value=EngagementTaskIntegrationStatus.SKIPPED,
            message=message,
        )

    # --- Step 4: nothing new -> no Concur call. ---
    if not selected_engagements:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No new engagements/tasks to sync (all already synced)",
        )

    # --- Step 5+6: bulk payload from the selection, then Concur create. ---
    bulk_payload = build_bulk_list_payload(selected_engagements)
    try:
        result = await SAPConcurEngagementTaskService().create_engagements_and_tasks(
            bulk_payload
        )
    except SAPConcurEngagementTaskServiceError as exc:
        # Transport/config failure: every sent item is FAILED, then 500.
        for jobnumber in sent_engagements:
            await _safe_create_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=jobnumber,
                maconomy_tasknumber="",
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=f"Engagement {jobnumber} creation failed: {exc}",
            )
        for jobnumber, tasknumber in sent_tasks:
            await _safe_create_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=jobnumber,
                maconomy_tasknumber=tasknumber,
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=(
                    f"Task {tasknumber} ({jobnumber}) creation failed: {exc}"
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # --- Step 7: process the bulk response -> mapping + per-item logs. ---
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

    for jobnumber in sent_engagements:
        key: tuple[str, ...] = ("eng", jobnumber)
        if failed_whole_run or key in failure_reasons:
            reason = failure_reasons.get(key) or (
                f"bulk request status {concur_status or 'UNKNOWN'}"
            )
            await _safe_create_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=jobnumber,
                maconomy_tasknumber="",
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=f"Engagement {jobnumber} creation failed: {reason}",
            )
            continue
        mapping_id = await _safe_create_mapping(
            session,
            maconomy_jobnumber=jobnumber,
            maconomy_tasknumber="",
        )
        await _safe_create_log(
            session,
            mapping_id=mapping_id,
            maconomy_jobnumber=jobnumber,
            maconomy_tasknumber="",
            status_value=EngagementTaskIntegrationStatus.SUCCESS,
            message=f"Engagement {jobnumber} created in SAP Concur",
        )

    for jobnumber, tasknumber in sent_tasks:
        key = ("task", jobnumber, tasknumber)
        if failed_whole_run or key in failure_reasons:
            reason = failure_reasons.get(key) or (
                f"bulk request status {concur_status or 'UNKNOWN'}"
            )
            await _safe_create_log(
                session,
                mapping_id=None,
                maconomy_jobnumber=jobnumber,
                maconomy_tasknumber=tasknumber,
                status_value=EngagementTaskIntegrationStatus.FAILED,
                message=(
                    f"Task {tasknumber} ({jobnumber}) creation failed: {reason}"
                ),
            )
            continue
        mapping_id = await _safe_create_mapping(
            session,
            maconomy_jobnumber=jobnumber,
            maconomy_tasknumber=tasknumber,
        )
        await _safe_create_log(
            session,
            mapping_id=mapping_id,
            maconomy_jobnumber=jobnumber,
            maconomy_tasknumber=tasknumber,
            status_value=EngagementTaskIntegrationStatus.SUCCESS,
            message=(
                f"Task {tasknumber} ({jobnumber}) created in SAP Concur"
            ),
        )

    # --- Step 8: the Concur response is returned verbatim. ---
    return result
