
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from app.features.auth.dependencies import require_api_key
from app.features.hubspot_integration.mappers.dynamic_field_mapper import (
    map_customers_to_company_upsert,
    map_customers_to_contact_upsert,
)
from app.features.hubspot_integration.services.hubspot_service import (
    HubSpotService,
    HubSpotServiceError,
)
from app.features.hubspot_integration.services.maconomy_service import (
    MaconomyService,
    MaconomyServiceError,
)


router = APIRouter(
    prefix="/hubspot",
    tags=["hubspot-integration"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/customers/recent")
async def get_recent_customers() -> dict[str, list[dict[str, Any]]]:
    """Retrieve recent Maconomy customers and classify them for HubSpot sync."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        service = MaconomyService(client)

        try:
            customers = await service.get_recent_customers()
            return service.classify_customers(customers)

        except MaconomyServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve customers from Maconomy",
            ) from exc


