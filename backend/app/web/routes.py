import uuid
from typing import Annotated
from urllib.parse import quote

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
from app.features.hubspot_integration.models import HubSpotIntegrationRunLog
from app.features.maconomy_caseware_cloud_intergration.models import (
    MaconomyCasewareRequestLog,
)
from app.features.paycor_integration.models import PaycorIntegrationLog
from app.features.sap_concur_integration.models import SAPConcurIntegrationLog
from app.features.user_activity.models import UserActivityLog
from app.features.user_activity.services import log_activity
from app.features.xcm_cch_axcess_integration.models import XCMCCHIntegrationRunLog
from app.features.xcm_cch_client_scoped_integration.models import (
    XCMCCHClientScopedRunLog,
)
from app.web.templating import templates

router = APIRouter(tags=["dashboard"])

_PAYCOR_INTEGRATION_IDENTIFIERS = {
    "PAYCOR_SYNC_EMPLOYEES",
    IntegrationServiceIdentifier.PAYCOR_SYNC_EMPLOYEES.value,
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

    await log_activity(
        session,
        action="enabled_service" if is_active else "disabled_service",
        user=current_user.username,
        service=integration.identifier_unique_name,
        status="SUCCESS",
    )

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
        await log_activity(
            session,
            action="manual_retry",
            user=current_user.username,
            service=integration.identifier_unique_name,
            data={"job_number": normalized_job_number, "integration_id": str(integration.id)},
            status="FAILED",
        )
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

    await log_activity(
        session,
        action="manual_retry",
        user=current_user.username,
        service=integration.identifier_unique_name,
        data={"job_number": normalized_job_number, "integration_id": str(integration.id)},
        status="SUCCESS",
    )
    _set_flash(request, success_message, "success")
    return redirect


@router.post(
    "/integrations/{integration_id}/retry-paycor-employee",
    name="retry_paycor_employee",
    include_in_schema=False,
)
async def retry_paycor_employee(
    integration_id: uuid.UUID,
    request: Request,
    current_user: AuthenticatedUser,
    csrf_token: Annotated[str, Form(min_length=1)],
    retry_action: Annotated[str, Form(min_length=1)],
    paycor_employee_id: Annotated[str, Form(min_length=1, max_length=36)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    """Manually retry a Paycor employee create or update synchronization."""
    if not valid_csrf_token(request, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired form token.",
        )

    result = await session.execute(
        select(IntegrationService).where(
            IntegrationService.id == integration_id,
            IntegrationService.identifier_unique_name.in_(
                _PAYCOR_INTEGRATION_IDENTIFIERS
            ),
            IntegrationService.is_deleted.is_(False),
        )
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paycor employee synchronization integration service not found.",
        )

    redirect = RedirectResponse(
        request.url_for("integration_logs", integration_id=integration.id),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    normalized_employee_id = paycor_employee_id.strip()
    try:
        employee_id = uuid.UUID(normalized_employee_id)
    except ValueError:
        _set_flash(request, "Enter a valid Paycor employee ID (UUID).", "danger")
        return redirect

    paths_by_action = {
        "create": "sync-with-maconomy",
        "update": "update-with-maconomy",
    }
    endpoint_action = paths_by_action.get(retry_action)
    if endpoint_action is None:
        _set_flash(request, "Select a valid Paycor retry action.", "danger")
        return redirect

    settings = get_settings()
    sync_path = (
        f"{settings.api_v1_prefix.rstrip('/')}/paycor/employees/"
        f"{employee_id}/{endpoint_action}"
    )
    activity_data = {
        "paycor_employee_id": str(employee_id),
        "retry_action": retry_action,
        "integration_id": str(integration.id),
    }
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
            response = await client.post(sync_path)
    except httpx.RequestError:
        await log_activity(
            session,
            action="manual_retry",
            user=current_user.username,
            service=integration.identifier_unique_name,
            data=activity_data,
            status="FAILED",
        )
        _set_flash(
            request,
            "The Paycor integration API could not be reached. Please try again.",
            "danger",
        )
        return redirect

    payload_value = _json_response_value(response)
    payload = payload_value if isinstance(payload_value, dict) else {}
    if not response.is_success:
        await log_activity(
            session,
            action="manual_retry",
            user=current_user.username,
            service=integration.identifier_unique_name,
            data=activity_data,
            status="FAILED",
        )
        _set_flash(
            request,
            _internal_api_error(payload, response.status_code),
            "danger",
        )
        return redirect

    await log_activity(
        session,
        action="manual_retry",
        user=current_user.username,
        service=integration.identifier_unique_name,
        data=activity_data,
        status="SUCCESS",
    )
    operation = "create" if retry_action == "create" else "update"
    _set_flash(
        request,
        f"Paycor employee {employee_id} {operation} retry completed successfully.",
        "success",
    )
    return redirect


@router.post(
    "/integrations/{integration_id}/retry-sap-concur-expense-report",
    name="retry_sap_concur_expense_report",
    include_in_schema=False,
)
async def retry_sap_concur_expense_report(
    integration_id: uuid.UUID,
    request: Request,
    current_user: AuthenticatedUser,
    csrf_token: Annotated[str, Form(min_length=1)],
    report_id: Annotated[str, Form(min_length=1, max_length=200)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    """Manually retry one SAP Concur expense report synchronization."""
    if not valid_csrf_token(request, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired form token.",
        )

    result = await session.execute(
        select(IntegrationService).where(
            IntegrationService.id == integration_id,
            IntegrationService.identifier_unique_name
            == IntegrationServiceIdentifier.MACONOMY_SAP_CONCUR_EXPENSE_SYNC.value,
            IntegrationService.is_deleted.is_(False),
        )
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SAP Concur expense synchronization integration service not found.",
        )

    redirect = RedirectResponse(
        request.url_for("integration_logs", integration_id=integration.id),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    normalized_report_id = report_id.strip()
    if not normalized_report_id:
        _set_flash(request, "Enter a valid SAP Concur report ID.", "danger")
        return redirect

    settings = get_settings()
    sync_path = (
        f"{settings.api_v1_prefix.rstrip('/')}"
        "/sap-concur/retry-expense-report-sync"
    )
    activity_data = {
        "report_id": normalized_report_id,
        "integration_id": str(integration.id),
    }
    try:
        async with httpx.AsyncClient(
            base_url=settings.scheduler_api_url,
            headers={
                "X-API-KEY": settings.scheduler_api_key.get_secret_value(),
                "X-Request-ID": str(request.state.request_id),
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(settings.scheduler_request_timeout_seconds),
        ) as client:
            response = await client.post(
                sync_path,
                json={"report_id": normalized_report_id},
            )
    except httpx.RequestError:
        await log_activity(
            session,
            action="manual_retry",
            user=current_user.username,
            service=integration.identifier_unique_name,
            data=activity_data,
            status="FAILED",
        )
        _set_flash(
            request,
            "The SAP Concur integration API could not be reached. Please try again.",
            "danger",
        )
        return redirect

    payload_value = _json_response_value(response)
    payload = payload_value if isinstance(payload_value, dict) else {}
    if not response.is_success:
        await log_activity(
            session,
            action="manual_retry",
            user=current_user.username,
            service=integration.identifier_unique_name,
            data=activity_data,
            status="FAILED",
        )
        _set_flash(
            request,
            _internal_api_error(payload, response.status_code),
            "danger",
        )
        return redirect

    retry_status = str(payload.get("status") or "FAILED").upper()
    retry_message = str(
        payload.get("message")
        or f"SAP Concur expense report {normalized_report_id} retry completed."
    )
    activity_status = {
        "SUCCESS": "SUCCESS",
        "SKIPPED": "SUCCESS",
        "PARTIALLY_SUCCESS": "PARTIAL_SUCCESS",
    }.get(retry_status, "FAILED")
    flash_category = {
        "SUCCESS": "success",
        "SKIPPED": "warning",
        "PARTIALLY_SUCCESS": "warning",
    }.get(retry_status, "danger")
    await log_activity(
        session,
        action="manual_retry",
        user=current_user.username,
        service=integration.identifier_unique_name,
        data=activity_data,
        status=activity_status,
    )
    _set_flash(request, retry_message, flash_category)
    return redirect


@router.post(
    "/integrations/{integration_id}/retry-hubspot-record",
    name="retry_hubspot_record",
    include_in_schema=False,
)
async def retry_hubspot_record(
    integration_id: uuid.UUID,
    request: Request,
    current_user: AuthenticatedUser,
    csrf_token: Annotated[str, Form(min_length=1)],
    record_type: Annotated[str, Form(min_length=1)],
    record_number: Annotated[str, Form(min_length=1, max_length=100)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    """Manually retry one HubSpot Customer or Contact Person sync."""
    if not valid_csrf_token(request, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired form token.",
        )

    result = await session.execute(
        select(IntegrationService).where(
            IntegrationService.id == integration_id,
            IntegrationService.identifier_unique_name
            == IntegrationServiceIdentifier.MACONOMY_HUBSPOT_SYNC.value,
            IntegrationService.is_deleted.is_(False),
        )
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HubSpot synchronization integration service not found.",
        )

    redirect = RedirectResponse(
        request.url_for("integration_logs", integration_id=integration.id),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    normalized_type = record_type.strip().lower()
    normalized_number = record_number.strip()
    path_segments = {
        "customer": "customers",
        "contact": "contacts",
    }
    path_segment = path_segments.get(normalized_type)
    if path_segment is None or not normalized_number:
        _set_flash(
            request,
            "Select Customer or Contact Person and enter a valid number.",
            "danger",
        )
        return redirect

    settings = get_settings()
    encoded_number = quote(normalized_number, safe="")
    sync_path = (
        f"{settings.api_v1_prefix.rstrip('/')}/hubspot/"
        f"{path_segment}/{encoded_number}/sync"
    )
    activity_data = {
        "record_type": normalized_type,
        "integration_id": str(integration.id),
    }
    try:
        async with httpx.AsyncClient(
            base_url=settings.scheduler_api_url,
            headers={
                "X-API-KEY": settings.scheduler_api_key.get_secret_value(),
                "X-Request-ID": str(request.state.request_id),
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(settings.scheduler_request_timeout_seconds),
        ) as client:
            response = await client.post(sync_path)
    except httpx.RequestError:
        await log_activity(
            session,
            action="manual_retry",
            user=current_user.username,
            service=integration.identifier_unique_name,
            data=activity_data,
            status="FAILED",
        )
        _set_flash(
            request,
            "The HubSpot integration API could not be reached. Please try again.",
            "danger",
        )
        return redirect

    payload_value = _json_response_value(response)
    payload = payload_value if isinstance(payload_value, dict) else {}
    if not response.is_success:
        await log_activity(
            session,
            action="manual_retry",
            user=current_user.username,
            service=integration.identifier_unique_name,
            data=activity_data,
            status="FAILED",
        )
        _set_flash(
            request,
            _internal_api_error(payload, response.status_code),
            "danger",
        )
        return redirect

    retry_status = str(payload.get("status") or "success")
    await log_activity(
        session,
        action="manual_retry",
        user=current_user.username,
        service=integration.identifier_unique_name,
        data=activity_data,
        status="SUCCESS" if retry_status == "success" else "PARTIAL_SUCCESS",
    )
    record_label = "Customer" if normalized_type == "customer" else "Contact Person"
    if retry_status == "partial_success":
        _set_flash(
            request,
            f"{record_label} retry completed with some synchronization errors.",
            "warning",
        )
    else:
        _set_flash(
            request,
            f"{record_label} was synchronized with HubSpot successfully.",
            "success",
        )
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

    await log_activity(
        session,
        action="opened_monitoring",
        user=current_user.username,
        service=integration.identifier_unique_name,
    )

    flash_message = request.session.pop("flash_message", None)
    flash_category = request.session.pop("flash_category", "success")
    print("Integration Logs", "*"*50)
    print(integration.identifier_unique_name)
    if integration.identifier_unique_name == IntegrationServiceIdentifier.PAYCOR_SYNC_EMPLOYEES.value:
        print("Paycor Logs","*"*50)
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
        print("*"*50)
        print(total_logs)
        print("*"*50)
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

    if (
        integration.identifier_unique_name
        == IntegrationServiceIdentifier.MACONOMY_HUBSPOT_SYNC.value
    ):
        run_result = await session.execute(
            select(HubSpotIntegrationRunLog)
            .order_by(HubSpotIntegrationRunLog.started_on_utc.desc())
            .limit(250)
        )
        run_logs = list(run_result.scalars().all())
        successful_runs = sum(log.status == "SUCCESS" for log in run_logs)
        total_runs = len(run_logs)

        return templates.TemplateResponse(
            request=request,
            name="maconomy_hubspot_dashboard.html",
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
                    "records_succeeded": sum(
                        log.customers_succeeded + log.contacts_succeeded
                        for log in run_logs
                    ),
                    "attention_required": sum(
                        log.failed_count + log.skipped_count
                        for log in run_logs
                    ),
                    "latest_run": run_logs[0] if run_logs else None,
                },
                "flash_message": flash_message,
                "flash_category": flash_category,
            },
        )

    if (
        integration.identifier_unique_name
        == IntegrationServiceIdentifier.MACONOMY_SAP_CONCUR_EXPENSE_SYNC.value
    ):
        log_result = await session.execute(
            select(SAPConcurIntegrationLog)
            .options(
                selectinload(SAPConcurIntegrationLog.expensesheet_expensereport_mapping)
            )
            .order_by(SAPConcurIntegrationLog.created_on_utc.desc())
            .limit(1000)
        )
        activity_logs = list(log_result.scalars().all())
        successful_logs = sum(
            log.status.value == "SUCCESS" for log in activity_logs
        )
        total_logs = len(activity_logs)

        return templates.TemplateResponse(
            request=request,
            name="sap_concur_dashboard.html",
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


@router.get(
    "/user-activities",
    response_class=HTMLResponse,
    name="user_activities",
    include_in_schema=False,
)
async def user_activities(
    request: Request,
    current_user: AuthenticatedUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: str | None = None,
) -> HTMLResponse:
    flash_message = request.session.pop("flash_message", None)
    flash_category = request.session.pop("flash_category", "success")

    query = select(UserActivityLog).order_by(UserActivityLog.created_on_utc.desc())
    if user:
        query = query.where(UserActivityLog.user == user)
    result = await session.execute(query.limit(500))
    activity_logs = list(result.scalars().all())

    distinct_result = await session.execute(
        select(UserActivityLog.user)
        .where(
            ~(
                (UserActivityLog.action == "login")
                & (UserActivityLog.status == "FAILED")
            )
        )
        .distinct()
        .order_by(UserActivityLog.user)
    )
    distinct_users = [row[0] for row in distinct_result.all()]

    return templates.TemplateResponse(
        request=request,
        name="user_activities.html",
        context={
            "current_user": current_user,
            "csrf_token": ensure_csrf_token(request),
            "activity_logs": activity_logs,
            "distinct_users": distinct_users,
            "selected_user": user,
            "flash_message": flash_message,
            "flash_category": flash_category,
        },
    )


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
