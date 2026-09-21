import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.integration_services import (
    IntegrationServiceIdentifier,
    require_active_integration_service,
)
from app.features.xcm_cch_axcess_integration.services import (
    CCHXCMService,
    CCHXCMServiceError,
    MaconomyService,
    MaconomyServiceError,
    integration_run_log_service,
)

router = APIRouter(
    prefix="/xcm-cch-axcess",
    tags=["xcm-cch-axcess-integration"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/maconomy-tax-engagements/pending-cch-task-mapping",
    response_model=list[dict[str, Any]],
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_CCH_XCM_TASK_MAPPING
            )
        )
    ],
)
async def process_pending_cch_task_mappings(
    request: Request,
    session: DatabaseSession,
) -> list[dict[str, Any]]:
    """Discover TAX jobs and resolve their existing or newly created CCH task."""
    request_id = getattr(request.state, "request_id", uuid.uuid4())
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.UUID(str(request_id))
    run_log = await integration_run_log_service.start_run(
        session,
        request_id=request_id,
        maconomy_instance=get_settings().maconomy_shortname,
    )

    try:
        jobs = await MaconomyService().get_syncable_tax_jobs()
    except MaconomyServiceError as exc:
        await integration_run_log_service.fail_run(
            session,
            run_log,
            failure_stage="MACONOMY_DISCOVERY",
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve pending tax engagements from Maconomy",
        ) from exc

    try:
        resolved_jobs = await CCHXCMService().resolve_tasks(jobs)
    except CCHXCMServiceError as exc:
        await integration_run_log_service.fail_run(
            session,
            run_log,
            failure_stage="CCH_AUTHENTICATION",
            error_message=str(exc),
            jobs_discovered=len(jobs),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to search or create tasks in CCH/XCM",
        ) from exc

    try:
        updated_jobs = await MaconomyService().update_cch_task_mappings(
            resolved_jobs
        )
    except MaconomyServiceError as exc:
        await integration_run_log_service.fail_run(
            session,
            run_log,
            failure_stage="MACONOMY_AUTHENTICATION",
            error_message=str(exc),
            jobs_discovered=len(jobs),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to save the CCH task mapping in Maconomy",
        ) from exc

    await integration_run_log_service.complete_run_from_jobs(
        session,
        run_log,
        updated_jobs,
    )
    return updated_jobs
