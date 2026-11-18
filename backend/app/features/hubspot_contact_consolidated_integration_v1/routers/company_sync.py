"""Entry point for the new consolidated HubSpot Company flow."""

from fastapi import APIRouter, Depends, HTTPException

from app.features.auth.dependencies import require_api_key
from app.features.integration_services import (
    IntegrationServiceIdentifier,
    require_active_integration_service,
)

router = APIRouter(
    prefix="/hubspot-consolidated",
    tags=["hubspot-consolidated-integration-v1"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "/companies/{maconomy_customer_number}/sync",
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_HUBSPOT_CONTACT_CONSOLIDATED_SYNC
            )
        )
    ],
)
async def sync_company_by_customer_number_v1(
    maconomy_customer_number: str,
) -> None:
    """Placeholder for syncing one Maconomy Customer."""
    raise HTTPException(
        status_code=501,
        detail="The v1 Company sync flow is not implemented yet",
    )
