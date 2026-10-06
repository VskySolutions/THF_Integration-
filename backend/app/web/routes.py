import uuid
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.authentication.dependencies import AuthenticatedUser
from app.authentication.security import (
    ensure_csrf_token,
    valid_csrf_token,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.features.integration_services.constants import IntegrationServiceIdentifier
from app.features.integration_services.models import IntegrationService
from app.features.maconomy_caseware_cloud_intergration.models import (
    MaconomyCasewareRequestLog,
)
from app.features.paycor_integration.models import PaycorIntegrationLog
from app.features.xcm_cch_axcess_integration.models import XCMCCHIntegrationRunLog
from app.features.xcm_cch_client_scoped_integration.models import (
    XCMCCHClientScopedRunLog,
)
from app.web.templating import templates

router = APIRouter(tags=["dashboard"])

_PAYCOR_INTEGRATION_IDENTIFIERS = {
    "PAYCOR_SYNC_EMPLOYEES",
    IntegrationServiceIdentifier.PAYCOR_SYNC_ONBOARDING_EMPLOYEES.value,
}


@router.get("/", include_in_schema=False)
async def index() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=307)


@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    name="dashboard",
    include_in_schema=False,
)
async def dashboard(
    request: Request,
    current_user: AuthenticatedUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    result = await session.execute(
        select(IntegrationService)
        .where(IntegrationService.is_deleted.is_(False))
        .order_by(IntegrationService.display_name)
    )
    integrations = list(result.scalars().all())
    flash_message = request.session.pop("flash_message", None)
    flash_category = request.session.pop("flash_category", "success")

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "current_user": current_user,
            "csrf_token": ensure_csrf_token(request),
            "integrations": integrations,
            "active_count": sum(service.is_active for service in integrations),
            "flash_message": flash_message,
            "flash_category": flash_category,
        },
    )


@router.post(
    "/integrations/{integration_id}/status",
    name="update_integration_status",
    include_in_schema=False,
)
async def update_integration_status(
    integration_id: uuid.UUID,
    request: Request,
    current_user: AuthenticatedUser,
    csrf_token: Annotated[str, Form(min_length=1)],
    is_active: Annotated[bool, Form()],
    session: Annotated[AsyncSession, Depends(get_db)],
    return_to: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    if not valid_csrf_token(request, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired form token.",
        )

    result = await session.execute(
        select(IntegrationService).where(
            IntegrationService.id == integration_id,
            IntegrationService.is_deleted.is_(False),
        )
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration service not found.",
        )

    integration.is_active = is_active
    integration.updated_on_utc = func.now()
    await session.commit()

    state = "activated" if is_active else "inactivated"
    request.session["flash_message"] = (
        f"{integration.display_name} was {state} successfully."
    )
    request.session["flash_category"] = "success"
    destination = (
        request.url_for("integration_logs", integration_id=integration.id)
        if return_to == "integration"
        else request.url_for("dashboard")
    )
    return RedirectResponse(
        destination, status_code=status.HTTP_303_SEE_OTHER
    )


@router.post(
    "/integrations/{integration_id}/sync-job",
    name="sync_caseware_job",
    include_in_schema=False,
)
async def sync_caseware_job(
    integration_id: uuid.UUID,
    request: Request,
    current_user: AuthenticatedUser,
    csrf_token: Annotated[str, Form(min_length=1)],
    job_number: Annotated[str, Form(min_length=1, max_length=100)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    if not valid_csrf_token(request, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired form token.",
        )

    result = await session.execute(
        select(IntegrationService).where(
            IntegrationService.id == integration_id,
            IntegrationService.identifier_unique_name.in_(
                (
                    IntegrationServiceIdentifier.MACONOMY_CASEWARE_CLOUD_SYNC.value,
                    IntegrationServiceIdentifier.MACONOMY_CCH_XCM_TASK_MAPPING.value,
                    IntegrationServiceIdentifier.MACONOMY_CCH_XCM_CLIENT_SCOPED.value,
                )
            ),
            IntegrationService.is_deleted.is_(False),
        )
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job synchronization integration service not found.",
        )

    redirect = RedirectResponse(
        request.url_for("integration_logs", integration_id=integration.id),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    normalized_job_number = job_number.strip()
    if not normalized_job_number:
        _set_flash(request, "Enter a valid Maconomy job number.", "danger")
        return redirect

    settings = get_settings()
    is_caseware = (
        integration.identifier_unique_name
        == IntegrationServiceIdentifier.MACONOMY_CASEWARE_CLOUD_SYNC.value
    )
    is_client_scoped_cch = (
        integration.identifier_unique_name
        == IntegrationServiceIdentifier.MACONOMY_CCH_XCM_CLIENT_SCOPED.value
    )
    sync_path = (
        f"{settings.api_v1_prefix.rstrip('/')}/maconomy-caseware-cloud/sync-job"
        if is_caseware
        else (
            f"{settings.api_v1_prefix.rstrip('/')}/xcm-cch-client-scoped/sync"
            if is_client_scoped_cch
            else (
                f"{settings.api_v1_prefix.rstrip('/')}/xcm-cch-axcess/"
                "maconomy-tax-engagements/retry-cch-task-mapping"
            )
        )
    )
    request_payload: dict[str, object] = (
        {"jobnumbers": [normalized_job_number]}
        if is_client_scoped_cch
        else {"jobnumber": normalized_job_number}
    )
    try:
        async with httpx.AsyncClient(
            base_url=settings.scheduler_api_url,
            headers={
                "X-API-KEY": settings.scheduler_api_key.get_secret_value(),
                "X-Request-ID": str(request.state.request_id),
                "Accept": "*/*",
            },
            timeout=httpx.Timeout(settings.scheduler_request_timeout_seconds),
        ) as client:
            response = await client.post(
                sync_path,
                json=request_payload,
            )
    except httpx.RequestError:
        _set_flash(
            request,
            "The integration API could not be reached. Please try again.",
            "danger",
        )
        return redirect

    payload_value = _json_response_value(response)
    payload = payload_value if isinstance(payload_value, dict) else {}
    if not response.is_success:
        _set_flash(
            request,
            _internal_api_error(payload, response.status_code),
            "danger",
        )
        return redirect

    if is_client_scoped_cch:
        jobs = payload_value if isinstance(payload_value, list) else []
        if not jobs:
            _set_flash(
                request,
                f"Job {normalized_job_number} did not require CCH client sync "
                "or was not eligible.",
                "warning",
            )
            return redirect

        job = jobs[0] if isinstance(jobs[0], dict) else {}
        failure_message = _client_scoped_job_failure(job)
        if failure_message:
            _set_flash(
                request,
                f"Job {normalized_job_number}: {failure_message}",
                "danger",
            )
            return redirect
        success_message = (
            f"Job {normalized_job_number} was synchronized with CCH/XCM "
            "successfully."
        )
    elif is_caseware:
        sync_action = str(payload.get("syncAction", "completed"))
        if sync_action.upper() == "FAILED":
            message = str(
                payload.get("syncError")
                or "The job could not be synchronized."
            )
            _set_flash(
                request,
                f"Job {normalized_job_number}: {message}",
                "danger",
            )
            return redirect
        success_message = (
            f"Job {normalized_job_number} sync completed "
            f"({sync_action.replace('_', ' ').title()})."
        )
    else:
        success_message = (
            f"Job {normalized_job_number} was synchronized with CCH/XCM "
            "successfully."
        )

    _set_flash(request, success_message, "success")
    return redirect


@router.get(
    "/integrations/{integration_id}/logs",
    response_class=HTMLResponse,
    name="integration_logs",
    include_in_schema=False,
)
async def integration_logs(
    integration_id: uuid.UUID,
    request: Request,
    current_user: AuthenticatedUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    result = await session.execute(
        select(IntegrationService).where(
            IntegrationService.id == integration_id,
            IntegrationService.is_deleted.is_(False),
        )
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration service not found.",
        )
    flash_message = request.session.pop("flash_message", None)
    flash_category = request.session.pop("flash_category", "success")

    if integration.identifier_unique_name in _PAYCOR_INTEGRATION_IDENTIFIERS:
        log_result = await session.execute(
            select(PaycorIntegrationLog)
            .options(
                selectinload(PaycorIntegrationLog.employee_mapping_log)
            )
            .order_by(PaycorIntegrationLog.created_on_utc.desc())
            .limit(1000)
        )
        activity_logs = list(log_result.scalars().all())
        successful_logs = sum(
            log.status.value == "SUCCESS" for log in activity_logs
        )
        total_logs = len(activity_logs)

        return templates.TemplateResponse(
            request=request,
            name="paycor_dashboard.html",
            context={
                "current_user": current_user,
                "csrf_token": ensure_csrf_token(request),
                "integration": integration,
                "activity_logs": activity_logs,
                "metrics": {
                    "total_activity": total_logs,
                    "success_rate": (
                        round(successful_logs / total_logs * 100, 1)
                        if total_logs
                        else 0
                    ),
                    "created": sum(
                        log.action.value == "CREATE"
                        for log in activity_logs
                    ),
                    "failed": sum(
                        log.status.value == "FAILED"
                        for log in activity_logs
                    ),
                    "latest_activity": (
                        activity_logs[0] if activity_logs else None
                    ),
                },
                "flash_message": flash_message,
                "flash_category": flash_category,
            },
        )

    if (
        integration.identifier_unique_name
        == IntegrationServiceIdentifier.MACONOMY_CASEWARE_CLOUD_SYNC.value
    ):
        run_result = await session.execute(
            select(MaconomyCasewareRequestLog)
            .where(
                MaconomyCasewareRequestLog.job_number.is_(None),
                MaconomyCasewareRequestLog.action == "SYNC",
            )
            .order_by(MaconomyCasewareRequestLog.created_on_utc.desc())
            .limit(250)
        )
        job_result = await session.execute(
            select(MaconomyCasewareRequestLog)
            .where(MaconomyCasewareRequestLog.job_number.is_not(None))
            .order_by(MaconomyCasewareRequestLog.created_on_utc.desc())
            .limit(1000)
        )
        run_logs = list(run_result.scalars().all())
        job_logs = list(job_result.scalars().all())
        successful_runs = sum(log.status == "SUCCESS" for log in run_logs)
        total_runs = len(run_logs)

        return templates.TemplateResponse(
            request=request,
            name="maconomy_caseware_dashboard.html",
            context={
                "current_user": current_user,
                "csrf_token": ensure_csrf_token(request),
                "integration": integration,
                "run_logs": run_logs,
                "job_logs": job_logs,
                "metrics": {
                    "total_runs": total_runs,
                    "success_rate": (
                        round(successful_runs / total_runs * 100, 1)
                        if total_runs
                        else 0
                    ),
                    "jobs_processed": sum(
                        _detail_count(log, "processed") for log in run_logs
                    ),
                    "failed_jobs": sum(
                        _detail_count(log, "failed") for log in run_logs
                    ),
                    "latest_run": run_logs[0] if run_logs else None,
                },
                "flash_message": flash_message,
                "flash_category": flash_category,
            },
        )

    if (
        integration.identifier_unique_name
        == IntegrationServiceIdentifier.MACONOMY_CCH_XCM_CLIENT_SCOPED.value
    ):
        run_result = await session.execute(
            select(XCMCCHClientScopedRunLog)
            .order_by(XCMCCHClientScopedRunLog.started_on_utc.desc())
            .limit(250)
        )
        run_logs = list(run_result.scalars().all())
        successful_runs = sum(log.status == "SUCCESS" for log in run_logs)
        total_runs = len(run_logs)

        return templates.TemplateResponse(
            request=request,
            name="maconomy_cch_client_scoped_dashboard.html",
            context={
                "current_user": current_user,
                "csrf_token": ensure_csrf_token(request),
                "integration": integration,
                "run_logs": run_logs,
                "status_badges": {
                    "SUCCESS": "text-bg-success",
                    "PARTIAL_SUCCESS": "text-bg-warning",
                    "FAILED": "text-bg-danger",
                    "RUNNING": "text-bg-primary",
                },
                "metrics": {
                    "total_runs": total_runs,
                    "success_rate": (
                        round(successful_runs / total_runs * 100, 1)
                        if total_runs
                        else 0
                    ),
                    "jobs_succeeded": sum(
                        log.jobs_succeeded for log in run_logs
                    ),
                    "jobs_failed": sum(log.failed_count for log in run_logs),
                    "latest_run": run_logs[0] if run_logs else None,
                },
                "flash_message": flash_message,
                "flash_category": flash_category,
            },
        )

    if (
        integration.identifier_unique_name
        == IntegrationServiceIdentifier.MACONOMY_CCH_XCM_TASK_MAPPING.value
    ):
        run_result = await session.execute(
            select(XCMCCHIntegrationRunLog)
            .order_by(XCMCCHIntegrationRunLog.started_on_utc.desc())
            .limit(250)
        )
        run_logs = list(run_result.scalars().all())
        successful_runs = sum(log.status == "SUCCESS" for log in run_logs)
        total_runs = len(run_logs)

        return templates.TemplateResponse(
            request=request,
            name="maconomy_cch_dashboard.html",
            context={
                "current_user": current_user,
                "csrf_token": ensure_csrf_token(request),
                "integration": integration,
                "run_logs": run_logs,
                "status_badges": {
                    "SUCCESS": "text-bg-success",
                    "PARTIAL_SUCCESS": "text-bg-warning",
                    "FAILED": "text-bg-danger",
                    "RUNNING": "text-bg-primary",
                },
                "metrics": {
                    "total_runs": total_runs,
                    "success_rate": (
                        round(successful_runs / total_runs * 100, 1)
                        if total_runs
                        else 0
                    ),
                    "tasks_mapped": sum(
                        log.tasks_linked + log.tasks_created for log in run_logs
                    ),
                    "attention_required": sum(
                        max(
                            log.manual_review_count + log.failed_count,
                            1 if log.failure_stage else 0,
                        )
                        for log in run_logs
                    ),
                    "latest_run": run_logs[0] if run_logs else None,
                },
                "flash_message": flash_message,
                "flash_category": flash_category,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="integration_logs_pending.html",
        context={
            "current_user": current_user,
            "csrf_token": ensure_csrf_token(request),
            "integration": integration,
            "flash_message": flash_message,
            "flash_category": flash_category,
        },
    )


@router.get(
    "/integrations/{integration_id}/runs/{request_id}/jobs",
    name="caseware_run_jobs",
    include_in_schema=False,
)
async def caseware_run_jobs(
    integration_id: uuid.UUID,
    request_id: uuid.UUID,
    current_user: AuthenticatedUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    integration_result = await session.execute(
        select(IntegrationService).where(
            IntegrationService.id == integration_id,
            IntegrationService.identifier_unique_name
            == IntegrationServiceIdentifier.MACONOMY_CASEWARE_CLOUD_SYNC.value,
            IntegrationService.is_deleted.is_(False),
        )
    )
    if integration_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CaseWare Cloud integration service not found.",
        )

    result = await session.execute(
        select(MaconomyCasewareRequestLog)
        .where(
            MaconomyCasewareRequestLog.request_id == request_id,
            MaconomyCasewareRequestLog.action != "SYNC",
        )
        .order_by(
            MaconomyCasewareRequestLog.created_on_utc.asc(),
            MaconomyCasewareRequestLog.job_number.asc(),
        )
    )
    logs = list(result.scalars().all())
    return {
        "request_id": str(request_id),
        "jobs": [_caseware_job_log_payload(log) for log in logs],
    }


def _detail_count(log: MaconomyCasewareRequestLog, key: str) -> int:
    value = (log.details or {}).get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _caseware_job_log_payload(
    log: MaconomyCasewareRequestLog,
) -> dict[str, object | None]:
    details = log.details if isinstance(log.details, dict) else {}
    checkpoint = details.get("text19")
    checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
    return {
        "job_number": log.job_number,
        "action": log.action,
        "status": log.status,
        "message": log.message,
        "version_number": details.get("versionnumber"),
        "entity_number": checkpoint.get("entityNo"),
        "entity_id": checkpoint.get("entityId"),
        "created_on_utc": log.created_on_utc.isoformat(),
    }


def _set_flash(request: Request, message: str, category: str) -> None:
    request.session["flash_message"] = message
    request.session["flash_category"] = category


def _json_response_value(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return {}


def _client_scoped_job_failure(job: dict[str, object]) -> str | None:
    stages = (
        ("CCH client creation", job.get("cchclientcreation")),
        ("CCH task creation", job.get("cchtaskcreation")),
    )
    for stage_name, stage_value in stages:
        if not isinstance(stage_value, dict):
            return f"{stage_name} result was not recorded."
        if stage_value.get("status") != "created":
            reason = stage_value.get("error") or f"{stage_name} failed."
            return str(reason)

    if job.get("maconomywritebackstatus") != "updated":
        reason = job.get("maconomywritebackerror")
        return str(reason or "Maconomy writeback failed.")
    return None


def _internal_api_error(payload: dict[str, object], status_code: int) -> str:
    detail = payload.get("detail")
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str):
            return message
    if isinstance(detail, str):
        return detail
    return f"The job sync request failed with status {status_code}."
