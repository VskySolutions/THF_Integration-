"""Entry point for the new consolidated HubSpot Contact flow."""

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
    "/contacts/{maconomy_contact_person_number}/sync",
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_HUBSPOT_CONTACT_CONSOLIDATED_SYNC
            )
        )
    ],
)
async def sync_contact_by_contact_person_number_v1(
    maconomy_contact_person_number: str,
) -> None:
    """Placeholder for syncing one Maconomy Contact Person."""
    raise HTTPException(
        status_code=501,
        detail="The v1 Contact sync flow is not implemented yet",
    )
