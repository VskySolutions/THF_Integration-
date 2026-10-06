from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from app.features.auth.dependencies import require_api_key
from app.features.integration_services import (
    IntegrationServiceIdentifier,
    require_active_integration_service,
)
from app.features.xcm_cch_client_scoped_integration.services.cch_client_service import (
    CCHClientService,
    CCHClientServiceError,
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
) -> list[dict[str, Any]]:
    """Create CCH clients for missing Maconomy jobs and return their details."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            maconomy = MaconomyService(client)
            await maconomy.authenticate()
            jobs = await maconomy.get_syncable_tax_jobs(payload.jobnumbers)
            if not jobs:
                return []
            cch = CCHClientService(client)
            flagged_jobs = await cch.flag_existing_clients(jobs[:40])
            new_cch_clients = [
                job for job in flagged_jobs if job["is_exist_in_chh"] is False
            ]
            if not new_cch_clients:
                return []
            reference_data = await maconomy.get_client_reference_records(new_cch_clients)
            enriched_jobs = maconomy.join_client_reference_records(
                new_cch_clients, reference_data
            )
            processed_jobs = await cch.create_clients_and_tasks(enriched_jobs)
            return await maconomy.update_cch_processing_results(processed_jobs)

    except MaconomyServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve eligible jobs from Maconomy",
        ) from exc
    except CCHClientServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unable to process clients or tasks in CCH/XCM: {exc}",
        ) from exc
