"""CCH Axcess engagement creation routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key

from app.features.cch_axcess_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)
from app.features.cch_axcess_integration.models import (
    CCHAxcessEntityEngagementMapping,
)

from app.features.cch_axcess_integration.schemas import (
    CreateCCHJobRequest,
)

from app.features.cch_axcess_integration.services import (
    MaconomyService,
    MaconomyServiceError,
    entity_engagement_mapping_service,
    integration_log_service,
)
from app.features.cch_axcess_integration.services.cch_axcess_service import CCHAxcessService, CCHAxcessServiceError


# Router
router = APIRouter(
    prefix="/cch-axcess",
    tags=["cch-axcess-integration"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]

@router.post(
    "/cch-axcess-test",
    response_model=dict[str, Any]
)
async def cch_axcess_test():
    return {
        "message": "CCH Axcess Integration"
    }


@router.post(
    "/sync-todays-created-maconomy-engagements-with-cch-axcess",
    response_model=list[dict[str, Any]],
)
async def sync_todays_created_maconomy_engagements_with_cch_axcess(
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
            cch_result = await _create_engagement(
                job_number,
                session,
                action_from="CRONJOB",
            )

            results.append({
                "job_number": job_number,
                "status": "SUCCESS" if cch_result else "SKIPPED",
                "result": cch_result,
            })

        except HTTPException as exc:
            await session.rollback()
            results.append({
                "job_number": job_number,
                "status": "FAILED",
                "message": exc.detail,
            })

        except Exception as exc:
            await session.rollback()
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
    This function handles the creation of a CCH Client based on a Maconomy job number.
    It checks for existing mappings, retrieves job details from Maconomy, and interacts with the CCh service to create or reconcile the client and its address.
    """

    # Check if mapping exists for the given Maconomy job number
    existing_mapping = (
        await entity_engagement_mapping_service.get_mapping_by_job_number(
            session, job_number
        )
    )
    if existing_mapping is not None:
        # Mapping already exists — verify the CCH client is accessible
        cch_service = CCHAxcessService()
        try:
            client_detail = await cch_service.get_client_by_id(
                existing_mapping.cch_axcess_entity_cchid
            )
        except Exception as exc:
            await _save_integration_log(
                session,
                job_number,
                IntegrationAction.CREATE,
                IntegrationStatus.FAILED,
                f"Failed to verify existing CCH client: {str(exc)}",
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to verify existing CCH client",
            ) from exc

        if client_detail is not None:
            message = (
                "CCH Axcess Client already exists for this Maconomy Job number"
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
            "Job is a template and cannot be created in CCH Axcesss",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job is a template and cannot be created in CCH Axcesss",
        )

    # ================ CCH Processing ================
    
    cch_service = CCHAxcessService()
    mapping = existing_mapping
    is_new_client = mapping is None
    client_was_reconciled = False

    if is_new_client:
        try:
            cch_result = await cch_service.create_client(job_detail)
        except CCHAxcessServiceError as exc:
            await _raise_client_creation_error(session, job_number, exc)

        # Create mapping after successful creation
        mapping = await entity_engagement_mapping_service.create_mapping(
            session,
            job_number=job_number,
            cch_client_id=cch_result["client_id"],
        )
    else:
        # If mapping exists, check if reconciliation is needed
        try:
            client_detail = await cch_service.get_client_by_id(mapping.cch_axcess_entity_cchid)
        except CCHAxcessServiceError as exc:
            await _raise_client_creation_error(session, job_number, exc)
        cch_result = {
            "client_id": client_detail["client_id"],
            # "Id": client_detail["Id"],
        }
        client_was_reconciled = True

        await integration_log_service.create_log(
            session,
            mapping_id=mapping.id,
            job_number=job_number,
            status=IntegrationStatus.SUCCESS,
            action=IntegrationAction.CREATE,
            message=(
                "CCH Axcess Client reconciled successfully"
                if client_was_reconciled
                else "CCH Axcess Client created successfully"
                if is_new_client
                else "Incomplete CCH Axcess create workflow resumed successfully"
            ),
        )
    return cch_result # job_detail

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


async def _raise_client_creation_error(
    session: AsyncSession,
    job_number: str,
    exc: CCHAxcessServiceError,
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
        detail="Unable to create or retrieve client in CCH Axcess",
    ) from exc


