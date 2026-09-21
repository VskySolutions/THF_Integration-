import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
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


class ManualCCHTaskMappingRequest(BaseModel):
    """Request body for retrying CCH task mapping for one Maconomy job."""

    jobnumber: str

    @field_validator("jobnumber")
    @classmethod
    def validate_jobnumber(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("jobnumber is required")
        return value


@router.post(
    "/maconomy-tax-engagements/retry-cch-task-mapping",
    response_model=dict[str, Any],
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_CCH_XCM_TASK_MAPPING
            )
        )
    ],
)
async def retry_cch_task_mapping(
    payload: ManualCCHTaskMappingRequest,
    request: Request,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Resolve and save the CCH task mapping for one eligible Maconomy job."""
    request_id = getattr(request.state, "request_id", uuid.uuid4())
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.UUID(str(request_id))
    run_log = await integration_run_log_service.start_run(
        session,
        request_id=request_id,
        maconomy_instance=get_settings().maconomy_shortname,
    )

    try:
        job = await MaconomyService().get_syncable_tax_job_by_number(
            payload.jobnumber
        )
    except MaconomyServiceError as exc:
        await integration_run_log_service.fail_run(
            session,
            run_log,
            failure_stage="MACONOMY_DISCOVERY",
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve the tax engagement from Maconomy",
        ) from exc

    if job is None:
        error_message = (
            f"Maconomy job {payload.jobnumber} was not found or is not eligible "
            "for CCH task mapping"
        )
        await integration_run_log_service.fail_run(
            session,
            run_log,
            failure_stage="MACONOMY_JOB_VALIDATION",
            error_message=error_message,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_message,
        )

    try:
        resolved_jobs = await CCHXCMService().resolve_tasks([job])
    except CCHXCMServiceError as exc:
        await integration_run_log_service.fail_run(
            session,
            run_log,
            failure_stage="CCH_AUTHENTICATION",
            error_message=str(exc),
            jobs_discovered=1,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to search or create the task in CCH/XCM",
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
            jobs_discovered=1,
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
    return updated_jobs[0]
