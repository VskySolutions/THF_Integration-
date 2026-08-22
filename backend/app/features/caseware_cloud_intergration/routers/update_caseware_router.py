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


@router.post(
    "/on-update-engagement-post",
    response_model=dict[str, Any],
)
async def on_update_post(
    payload: CreateCasewareJobRequest, session: DatabaseSession
) -> dict[str, Any]:
    return await _detect_engagement_update(payload.jobnumber, session)


async def _detect_engagement_update(
    job_number: str,
    session: AsyncSession,
) -> dict[str, Any]:
    mapping = await entity_engagement_mapping_service.get_mapping_by_job_number(
        session, job_number
    )
    if mapping is None:
        message = "CaseWare Cloud mapping not found for Maconomy job number"
        await integration_log_service.create_log(
            session,
            mapping_id=None,
            job_number=job_number,
            status=IntegrationStatus.FAILED,
            action=IntegrationAction.UPDATE,
            message=message,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message,
        )

    try:
        job_detail = await MaconomyService().get_job_detail_by_job_number(job_number)
    except MaconomyServiceError as exc:
        await integration_log_service.create_log(
            session,
            mapping_id=mapping.id,
            job_number=job_number,
            status=IntegrationStatus.FAILED,
            action=IntegrationAction.UPDATE,
            message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve job details from Maconomy",
        ) from exc

    if job_detail is None:
        await integration_log_service.create_log(
            session,
            mapping_id=mapping.id,
            job_number=job_number,
            status=IntegrationStatus.FAILED,
            action=IntegrationAction.UPDATE,
            message="Job not found",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    if job_detail.get("template") is True:
        message = "Engagement is a template and cannot be updated in CaseWare Cloud"
        await integration_log_service.create_log(
            session,
            mapping_id=mapping.id,
            job_number=job_number,
            status=IntegrationStatus.FAILED,
            action=IntegrationAction.UPDATE,
            message=message,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    try:
        maconomy_version = _parse_version_number(job_detail.get("versionnumber"))
    except ValueError as exc:
        message = "Invalid versionnumber received from Maconomy"
        await integration_log_service.create_log(
            session,
            mapping_id=mapping.id,
            job_number=job_number,
            status=IntegrationStatus.FAILED,
            action=IntegrationAction.UPDATE,
            message=message,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=message,
        ) from exc

    try:
        stored_version = _parse_version_number(mapping.maconomy_job_version_number)
    except ValueError as exc:
        message = "Invalid stored Maconomy job versionnumber"
        await integration_log_service.create_log(
            session,
            mapping_id=mapping.id,
            job_number=job_number,
            status=IntegrationStatus.FAILED,
            action=IntegrationAction.UPDATE,
            message=message,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=message,
        ) from exc

    if maconomy_version > stored_version:
        update_status = "UPDATE_REQUIRED"
    elif maconomy_version == stored_version:
        update_status = "UP_TO_DATE"
    else:
        update_status = "STALE_SOURCE_VERSION"

    await integration_log_service.create_log(
        session,
        mapping_id=mapping.id,
        job_number=job_number,
        status=IntegrationStatus.SUCCESS,
        action=IntegrationAction.UPDATE,
        message=(
            f"Update detection result: {update_status}; "
            f"stored versionnumber={stored_version}; "
            f"Maconomy versionnumber={maconomy_version}"
        ),
    )
    return {
        "jobnumber": job_number,
        "status": update_status,
        "stored_versionnumber": stored_version,
        "maconomy_versionnumber": maconomy_version,
    }


def _parse_version_number(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Version number must be a non-negative integer")

    if isinstance(value, int):
        version = value
    elif isinstance(value, str) and value.strip().isdigit():
        version = int(value.strip())
    else:
        raise ValueError("Version number must be a non-negative integer")

    if version < 0:
        raise ValueError("Version number must be a non-negative integer")
    return version
