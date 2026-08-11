from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.caseware_cloud_intergration.constants import (
    IntegrationAction,
    IntegrationStatus,
)
from app.features.caseware_cloud_intergration.schemas import (
    CreateCasewareJobRequest,
)
from app.features.caseware_cloud_intergration.services import (
    MaconomyService,
    MaconomyServiceError,
    entity_engagement_mapping_service,
    integration_log_service,
)

router = APIRouter(
    prefix="/caseware-cloud",
    tags=["caseware-cloud-integration"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/on-create-engagement-post", response_model=dict[str, Any])
async def on_create_new(
    payload: CreateCasewareJobRequest, session: DatabaseSession
) -> dict[str, Any]:
    return await _get_job_detail(payload.jobnumber, IntegrationAction.CREATE, session)


@router.post("/on-update-engagement-post", response_model=dict[str, Any])
async def on_update_post(
    payload: CreateCasewareJobRequest, session: DatabaseSession
) -> dict[str, Any]:
    return await _get_job_detail(payload.jobnumber, IntegrationAction.UPDATE, session)


async def _get_job_detail(
    job_number: str,
    action: IntegrationAction,
    session: AsyncSession,
) -> dict[str, Any]:
    maconomy_service = MaconomyService()
    try:
        job_detail = await maconomy_service.get_job_detail_by_job_number(job_number)

        if job_detail is not None:
            customer_number = job_detail.get("customernumber")
            customer_detail = {}
            if customer_number:
                customer_detail = (
                    await maconomy_service.get_client_detail_by_customer_number(
                        str(customer_number)
                    )
                    or {}
                )
            job_detail["customer"] = customer_detail
    except MaconomyServiceError as exc:
        await _save_integration_log(
            session,
            job_number,
            action,
            IntegrationStatus.FAILED,
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve job details from Maconomy",
        ) from exc

    if job_detail is None:
        await _save_integration_log(
            session,
            job_number,
            action,
            IntegrationStatus.FAILED,
            "Job not found",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    await _save_integration_log(
        session,
        job_number,
        action,
        IntegrationStatus.SUCCESS,
        "Job and customer details retrieved successfully",
    )
    return job_detail


async def _save_integration_log(
    session: AsyncSession,
    job_number: str,
    action: IntegrationAction,
    integration_status: IntegrationStatus,
    message: str,
) -> None:
    mapping = await entity_engagement_mapping_service.get_mapping_by_job_number(
        session, job_number
    )
    mapping_id = mapping.id if mapping else None
    await integration_log_service.create_log(
        session,
        mapping_id=mapping_id,
        job_number=job_number,
        status=integration_status,
        action=action,
        message=message,
    )
