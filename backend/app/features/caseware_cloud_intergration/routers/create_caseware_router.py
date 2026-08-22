"""CaseWare Cloud engagement creation routes."""

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
from app.features.caseware_cloud_intergration.services.caseware_cloud_service import (
    CasewareCloudService,
    CasewareCloudServiceError,
)

router = APIRouter(
    prefix="/caseware-cloud",
    tags=["caseware-cloud-integration"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/on-create-engagement-post", 
    response_model=dict[str, Any]
)
async def on_create_new(
    payload: CreateCasewareJobRequest, session: DatabaseSession
) -> dict[str, Any]:
    return await _create_engagement(payload.jobnumber, session)


@router.post(
    "/sync-todays-created-maconomy-engagements-with-caseware",
    response_model=list[dict[str, Any]],
)
async def sync_todays_created_maconomy_engagements_with_caseware(
    session: DatabaseSession,
) -> list[dict[str, Any]]:

    new_engagements = await MaconomyService().get_todays_new_from_maconomy()

    results: list[dict[str, Any]] = []

    for engagement in new_engagements or []:
        job_number = engagement.get("jobnumber")

        if not job_number:
            continue

        try:
            cw_result = await _create_engagement(
                job_number,
                session,
                action_from="CRONJOB",
            )

            results.append({
                "job_number": job_number,
                "status": "SUCCESS" if cw_result else "FAILED",
                "result": cw_result,
            })

        except HTTPException as exc:
            results.append({
                "job_number": job_number,
                "status": "FAILED",
                "message": exc.detail,
            })

        except Exception as exc:
            results.append({
                "job_number": job_number,
                "status": "FAILED",
                "message": str(exc),
            })

    return results


async def _create_engagement(job_number: str, session: AsyncSession, action_from:str = "CREATEAPI") -> dict[str, Any]:
    existing_mapping = (
        await entity_engagement_mapping_service.get_mapping_by_job_number(
            session, job_number
        )
    )
    if existing_mapping is not None:
        message = (
            "CaseWare Entity record is already created for this Maconomy Job number"
        )
        await integration_log_service.create_log(
            session,
            mapping_id=existing_mapping.id,
            job_number=job_number,
            status=IntegrationStatus.FAILED,
            action=IntegrationAction.CREATE,
            message=message,
        )
        if action_from == "CREATEAPI":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=message,
            )
        return None

    try:
        job_detail = await _fetch_maconomy_job(job_number)
    except MaconomyServiceError as exc:
        await _save_integration_log(
            session,
            job_number,
            IntegrationAction.CREATE,
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
            IntegrationAction.CREATE,
            IntegrationStatus.FAILED,
            "Job not found",
        )
        raise HTTPException(status_code=404, detail="Job not found")
    if job_detail.get("template") is True:
        await _save_integration_log(
            session,
            job_number,
            IntegrationAction.CREATE,
            IntegrationStatus.FAILED,
            "Job is a template and cannot be created in Caseware Cloud",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job is a template and cannot be created in Caseware Cloud",
        )

    # Create the Entity in Caseware Cloud
    caseware_service = CasewareCloudService()
    try:
        caseware_result = await caseware_service.create_entity(job_detail)
    except CasewareCloudServiceError as exc:
        await _save_integration_log(
            session,
            job_number,
            IntegrationAction.CREATE,
            IntegrationStatus.FAILED,
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create entity in Caseware Cloud",
        ) from exc

    mapping = await entity_engagement_mapping_service.create_mapping(
        session = session,
        caseware_cwid = str(caseware_result["CWGuid"]),
        job_number = job_number,
        maconomy_job_version_number = str(job_detail.get("versionnumber", 1))
    )

    # Caseware Cloud Entity Address Creation
    try:
        address_result = await caseware_service.create_entity_address(
            job_detail,
            str(caseware_result["CWGuid"]),
            int(caseware_result["Id"]),
        )
    except (CasewareCloudServiceError, TypeError, ValueError) as exc:
        message = "Caseware Cloud entity created but address was not created"
        await integration_log_service.create_log(
            session,
            mapping_id=mapping.id,
            job_number=job_number,
            status=IntegrationStatus.FAILED,
            action=IntegrationAction.CREATE,
            message=message,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=message,
        ) from exc

    await entity_engagement_mapping_service.set_mapping_addresses(
        session,
        mapping,
        [{
            "maconomy_customer_number": str(job_detail.get("customernumber", "")),
            "cw_address_id": str(address_result["Id"]),
            "caseware_cw_guid": str(address_result["CWGuid"]),
            "maconomy_customer_version_number": str(job_detail.get("versionnumber", 1)),
        }]
    )
    await integration_log_service.create_log(
        session,
        mapping_id=mapping.id,
        job_number=job_number,
        status=IntegrationStatus.SUCCESS,
        action=IntegrationAction.CREATE,
        message="Caseware Cloud entity and address created successfully",
    )
    return caseware_result


async def _fetch_maconomy_job(job_number: str) -> dict[str, Any] | None:
    return await MaconomyService().get_job_detail_by_job_number(job_number)


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
