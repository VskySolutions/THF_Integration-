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
from app.features.caseware_cloud_intergration.models import (
    CasewareCloudEntityEngagementMapping,
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
    CasewareCloudEntityCreationError,
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

    new_engagements = (
        await MaconomyService().get_yesterday_and_todays_new_from_maconomy()
    )

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
                "status": "SUCCESS" if cw_result else "SKIPPED",
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


async def _create_engagement(
    job_number: str, 
    session: AsyncSession, 
    action_from:str = "CREATEAPI"
) -> dict[str, Any]:
    """
    This function handles the creation of a CaseWare Cloud engagement based on a Maconomy job number.
    It checks for existing mappings, retrieves job details from Maconomy, and interacts with the CaseWare Cloud service to create or reconcile the engagement and its address.
    """

    # Check if mapping exists for the given Maconomy job number
    existing_mapping = (
        await entity_engagement_mapping_service.get_mapping_by_job_number(
            session, job_number
        )
    )
    if existing_mapping is not None:
        try:
            address_mapping = _get_single_address_mapping(existing_mapping)
            mapping_is_complete = _is_address_mapping_complete(address_mapping)
        except ValueError as exc:
            await _raise_invalid_mapping_error(
                session,
                existing_mapping,
                job_number,
                str(exc),
            )

        if mapping_is_complete:
            message = (
                "CaseWare Entity record is already created for this Maconomy Job "
                "number"
            )
            integration_status = (
                IntegrationStatus.FAILED
                if action_from == "CREATEAPI"
                else IntegrationStatus.SKIPPED
            )
            await integration_log_service.create_log(
                session,
                mapping_id=existing_mapping.id,
                job_number=job_number,
                status=integration_status,
                action=IntegrationAction.CREATE,
                message=message,
            )
            if action_from == "CREATEAPI":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=message,
                )
            return None

    # Retrieve job details from Maconomy
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

    caseware_service = CasewareCloudService()
    mapping = existing_mapping
    is_new_entity = mapping is None
    entity_was_reconciled = False

    if is_new_entity:
        try:
            caseware_result = await caseware_service.create_entity(job_detail)
        except CasewareCloudEntityCreationError as exc:
            if not exc.reconciliation_allowed:
                await _raise_entity_creation_error(session, job_number, exc)

            try:
                reconciled_entity = (
                    await caseware_service.get_entity_by_entity_number(job_number)
                )
            except CasewareCloudServiceError as reconciliation_exc:
                await _raise_entity_creation_error(
                    session,
                    job_number,
                    reconciliation_exc,
                )

            if reconciled_entity is None:
                await _raise_entity_creation_error(session, job_number, exc)

            caseware_result = {
                "CWGuid": str(reconciled_entity["CWGuid"]),
                "Id": int(reconciled_entity["Id"]),
            }
            entity_was_reconciled = True
        except CasewareCloudServiceError as exc:
            await _raise_entity_creation_error(session, job_number, exc)

        mapping = await entity_engagement_mapping_service.create_mapping(
            session=session,
            caseware_cwid=str(caseware_result["CWGuid"]),
            job_number=job_number,
            maconomy_job_version_number=str(job_detail.get("versionnumber", 1)),
        )
    else:
        try:
            entity_detail = await caseware_service.get_entity_detail(
                mapping.caseware_cloud_entity_cwid
            )
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
                detail="Unable to resume CaseWare Cloud entity creation",
            ) from exc
        caseware_result = {
            "CWGuid": str(entity_detail["CWGuid"]),
            "Id": int(entity_detail["Id"]),
        }

    try:
        address_result = await _ensure_entity_address(
            session=session,
            mapping=mapping,
            job_detail=job_detail,
            caseware_service=caseware_service,
            entity_cw_guid=str(caseware_result["CWGuid"]),
            entity_owner_id=int(caseware_result["Id"]),
            is_new_entity=is_new_entity and not entity_was_reconciled,
        )
    except (CasewareCloudServiceError, TypeError, ValueError) as exc:
        message = str(exc)
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

    await integration_log_service.create_log(
        session,
        mapping_id=mapping.id,
        job_number=job_number,
        status=IntegrationStatus.SUCCESS,
        action=IntegrationAction.CREATE,
        message=(
            "Caseware Cloud entity reconciled and address synchronized successfully"
            if entity_was_reconciled
            else "Caseware Cloud entity and address created successfully"
            if is_new_entity
            else "Incomplete Caseware Cloud create workflow resumed successfully"
        ),
    )
    return caseware_result


async def _ensure_entity_address(
    *,
    session: AsyncSession,
    mapping: CasewareCloudEntityEngagementMapping,
    job_detail: dict[str, Any],
    caseware_service: CasewareCloudService,
    entity_cw_guid: str,
    entity_owner_id: int,
    is_new_entity: bool,
) -> dict[str, int | str]:
    address_mapping = _get_single_address_mapping(mapping)

    if address_mapping is not None and address_mapping.get("cw_address_id"):
        address_id = _parse_address_id(address_mapping["cw_address_id"])
        address_result = await caseware_service.get_entity_address_by_id(
            entity_cw_guid,
            address_id,
        )
        await _save_complete_address_mapping(
            session,
            mapping,
            job_detail,
            address_result,
        )
        return address_result

    if address_mapping is not None and address_mapping.get("caseware_cw_guid"):
        raise ValueError("Invalid CaseWare Cloud address mapping: address ID is missing")

    if not is_new_entity:
        existing_addresses = await caseware_service.get_entity_addresses(
            entity_cw_guid
        )
        if len(existing_addresses) > 1:
            raise CasewareCloudServiceError(
                "CaseWare Cloud address mapping is ambiguous and requires manual resolution"
            )
        if len(existing_addresses) == 1:
            address_result = _address_result_from_record(existing_addresses[0])
            await _save_complete_address_mapping(
                session,
                mapping,
                job_detail,
                address_result,
            )
            return address_result

    created_address = await caseware_service.create_entity_address(
        job_detail,
        entity_cw_guid,
        entity_owner_id,
    )
    address_id = int(created_address["Id"])
    await entity_engagement_mapping_service.set_mapping_addresses(
        session,
        mapping,
        [_build_address_mapping(job_detail, address_id)],
    )

    try:
        address_result = await caseware_service.get_entity_address_by_id(
            entity_cw_guid,
            address_id,
        )
    except CasewareCloudServiceError as exc:
        raise CasewareCloudServiceError(
            "CaseWare Cloud address created but CWGuid retrieval failed"
        ) from exc

    await _save_complete_address_mapping(
        session,
        mapping,
        job_detail,
        address_result,
    )
    return address_result


async def _save_complete_address_mapping(
    session: AsyncSession,
    mapping: CasewareCloudEntityEngagementMapping,
    job_detail: dict[str, Any],
    address_result: dict[str, int | str],
) -> None:
    await entity_engagement_mapping_service.set_mapping_addresses(
        session,
        mapping,
        [
            _build_address_mapping(
                job_detail,
                int(address_result["Id"]),
                str(address_result["CWGuid"]),
            )
        ],
    )


def _build_address_mapping(
    job_detail: dict[str, Any],
    address_id: int,
    address_cw_guid: str | None = None,
) -> dict[str, str]:
    address_mapping = {
        "maconomy_customer_number": str(job_detail.get("customernumber", "")),
        "cw_address_id": str(address_id),
        "maconomy_customer_version_number": str(job_detail.get("versionnumber", 1)),
    }
    if address_cw_guid:
        address_mapping["caseware_cw_guid"] = address_cw_guid
    return address_mapping


def _get_single_address_mapping(
    mapping: CasewareCloudEntityEngagementMapping,
) -> dict[str, str] | None:
    addresses = mapping.cw_addresses
    if addresses is None or addresses == []:
        return None
    if not isinstance(addresses, list) or len(addresses) != 1:
        raise ValueError("Invalid CaseWare Cloud address mapping")
    address_mapping = addresses[0]
    if not isinstance(address_mapping, dict):
        raise ValueError("Invalid CaseWare Cloud address mapping")
    return address_mapping


def _is_address_mapping_complete(
    address_mapping: dict[str, str] | None,
) -> bool:
    if address_mapping is None:
        return False
    raw_address_id = address_mapping.get("cw_address_id")
    address_cw_guid = address_mapping.get("caseware_cw_guid")
    customer_number = address_mapping.get("maconomy_customer_number")
    customer_version = address_mapping.get("maconomy_customer_version_number")
    if not raw_address_id and not address_cw_guid:
        return False
    if raw_address_id:
        _parse_address_id(raw_address_id)
    if address_cw_guid and not raw_address_id:
        raise ValueError("Invalid CaseWare Cloud address mapping: address ID is missing")
    if address_cw_guid is not None and (
        not isinstance(address_cw_guid, str) or not address_cw_guid.strip()
    ):
        raise ValueError("Invalid CaseWare Cloud address CWGuid")
    return bool(
        raw_address_id
        and address_cw_guid
        and customer_number
        and customer_version
    )


def _parse_address_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Invalid CaseWare Cloud address ID")
    try:
        address_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid CaseWare Cloud address ID") from exc
    if address_id <= 0:
        raise ValueError("Invalid CaseWare Cloud address ID")
    return address_id


def _address_result_from_record(
    address: dict[str, Any],
) -> dict[str, int | str]:
    address_id = _parse_address_id(address.get("Id"))
    address_cw_guid = address.get("CWGuid")
    if not isinstance(address_cw_guid, str) or not address_cw_guid.strip():
        raise ValueError("Invalid CaseWare Cloud address CWGuid")
    return {
        "Id": address_id,
        "CWGuid": address_cw_guid,
    }


async def _raise_invalid_mapping_error(
    session: AsyncSession,
    mapping: CasewareCloudEntityEngagementMapping,
    job_number: str,
    message: str,
) -> None:
    await integration_log_service.create_log(
        session,
        mapping_id=mapping.id,
        job_number=job_number,
        status=IntegrationStatus.FAILED,
        action=IntegrationAction.CREATE,
        message=message,
    )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=message,
    )


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


async def _raise_entity_creation_error(
    session: AsyncSession,
    job_number: str,
    exc: CasewareCloudServiceError,
) -> None:
    await _save_integration_log(
        session,
        job_number,
        IntegrationAction.CREATE,
        IntegrationStatus.FAILED,
        str(exc),
    )
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Unable to create or reconcile entity in CaseWare Cloud",
    ) from exc
