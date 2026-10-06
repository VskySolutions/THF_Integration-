import uuid
from typing import Annotated, Any

import httpx
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
from app.features.xcm_cch_client_scoped_integration.services.cch_client_service import (
    CCHClientService,
    CCHClientServiceError,
)
from app.features.xcm_cch_client_scoped_integration.services import (
    integration_run_log_service,
)
from app.features.xcm_cch_client_scoped_integration.services.maconomy_service import (
    MaconomyService,
    MaconomyServiceError,
)


class ClientScopedSyncRequest(BaseModel):
    jobnumbers: list[str] | None = None

    @field_validator("jobnumbers")
    @classmethod
    def validate_jobnumbers(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [jobnumber.strip() for jobnumber in value]
        if any(not jobnumber for jobnumber in normalized):
            raise ValueError("jobnumbers must contain non-empty strings")
        return normalized


router = APIRouter(
    prefix="/xcm-cch-client-scoped",
    tags=["xcm-cch-client-scoped-integration"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/sync",
    response_model=list[dict[str, Any]],
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_CCH_XCM_CLIENT_SCOPED
            )
        )
    ],
)
async def sync_client_scoped_engagements(
    payload: ClientScopedSyncRequest,
    request: Request,
    session: DatabaseSession,
) -> list[dict[str, Any]]:
    """Create CCH clients for missing Maconomy jobs and return their details."""
    request_id = getattr(request.state, "request_id", uuid.uuid4())
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.UUID(str(request_id))
    trigger_header = request.headers.get("X-Integration-Trigger", "API").upper()
    trigger_type = "SCHEDULER" if trigger_header == "SCHEDULER" else "API"
    run_log = await integration_run_log_service.start_run(
        session,
        request_id=request_id,
        maconomy_instance=get_settings().maconomy_shortname,
        trigger_type=trigger_type,
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        maconomy = MaconomyService(client)
        try:
            await maconomy.authenticate()
            jobs = await maconomy.get_syncable_tax_jobs(payload.jobnumbers)
        except MaconomyServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="MACONOMY_DISCOVERY",
                error_message=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve eligible jobs from Maconomy",
            ) from exc

        if not jobs:
            await integration_run_log_service.complete_run_from_jobs(
                session,
                run_log,
                discovered_job_numbers=[],
                jobs=[],
            )
            return []

        selected_jobs = jobs[:40]
        maconomy_job_numbers = [
            str(job.get("jobnumber")) for job in selected_jobs
        ]
        cch = CCHClientService(client)
        try:
            flagged_jobs = await cch.flag_existing_clients(selected_jobs)
        except CCHClientServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="CCH_CLIENT_LOOKUP",
                error_message=str(exc),
                discovered_job_numbers=maconomy_job_numbers,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Unable to process clients or tasks in CCH/XCM: {exc}",
            ) from exc

        new_cch_clients = [
            job for job in flagged_jobs if job["is_exist_in_chh"] is False
        ]
        discovered_job_numbers = [
            str(job.get("jobnumber")) for job in new_cch_clients
        ]
        if not new_cch_clients:
            await integration_run_log_service.complete_run_from_jobs(
                session,
                run_log,
                discovered_job_numbers=[],
                jobs=[],
            )
            return []

        try:
            reference_data = await maconomy.get_client_reference_records(new_cch_clients)
            enriched_jobs = maconomy.join_client_reference_records(
                new_cch_clients, reference_data
            )
        except MaconomyServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="MACONOMY_REFERENCE_DATA",
                error_message=str(exc),
                discovered_job_numbers=discovered_job_numbers,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve eligible jobs from Maconomy",
            ) from exc

        try:
            processed_jobs = await cch.create_clients_and_tasks(enriched_jobs)
        except CCHClientServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="CCH_AUTHENTICATION",
                error_message=str(exc),
                discovered_job_numbers=discovered_job_numbers,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Unable to process clients or tasks in CCH/XCM: {exc}",
            ) from exc

        try:
            updated_jobs = await maconomy.update_cch_processing_results(processed_jobs)
        except MaconomyServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="MACONOMY_WRITEBACK",
                error_message=str(exc),
                discovered_job_numbers=discovered_job_numbers,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to save CCH processing results in Maconomy",
            ) from exc

        await integration_run_log_service.complete_run_from_jobs(
            session,
            run_log,
            discovered_job_numbers=discovered_job_numbers,
            jobs=updated_jobs,
        )
        return updated_jobs
