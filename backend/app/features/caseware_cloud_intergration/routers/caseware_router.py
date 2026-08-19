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


@router.post("/on-create-engagement-post", response_model=dict[str, Any])
async def on_create_new(
    payload: CreateCasewareJobRequest, session: DatabaseSession
) -> dict[str, Any]:
    return await _create_engagement(payload.jobnumber, session)


@router.post("/on-update-engagement-post", response_model=dict[str, Any])
async def on_update_post(
    payload: CreateCasewareJobRequest, session: DatabaseSession
) -> dict[str, Any]:
    return await _get_job_detail(payload.jobnumber, session)


async def _create_engagement(job_number: str, session: AsyncSession) -> dict[str, Any]:
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=message,
        )

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

    try:
        job_detail = await _add_customer_detail(job_detail)
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
            detail="Unable to retrieve customer details from Maconomy",
        ) from exc

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
    customer_detail = job_detail.get("customer", {})
    try:
        address_result = await caseware_service.create_entity_address(
            customer_detail,
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
        #[address_result["Id"]],
        [{
            "maconomy_customer_number": customer_detail.get("customernumber", ""),
            "cw_address_id": str(address_result["Id"]),
            "maconomy_customer_version_number": str(customer_detail.get("versionnumber", 1)),
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


async def _get_job_detail(
    job_number: str,
    session: AsyncSession,
) -> dict[str, Any]:
    try:
        job_detail = await _fetch_maconomy_job(job_number)
        if job_detail is not None:
            job_detail = await _add_customer_detail(job_detail)
    except MaconomyServiceError as exc:
        await _save_integration_log(
            session,
            job_number,
            IntegrationAction.UPDATE,
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
            IntegrationAction.UPDATE,
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
        IntegrationAction.UPDATE,
        IntegrationStatus.SUCCESS,
        "Job and customer details retrieved successfully",
    )
    return job_detail


async def _fetch_maconomy_job(job_number: str) -> dict[str, Any] | None:
    return await MaconomyService().get_job_detail_by_job_number(job_number)


async def _add_customer_detail(job_detail: dict[str, Any]) -> dict[str, Any]:
    customer_number = job_detail.get("customernumber")
    customer_detail = {}
    if customer_number:
        customer_detail = (
            await MaconomyService().get_client_detail_by_customer_number(
                str(customer_number)
            )
            or {}
        )
    job_detail["customer"] = customer_detail
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
