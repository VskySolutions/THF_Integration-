
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from app.features.auth.dependencies import require_api_key
from app.features.hubspot_integration.services.maconomy_service import (
    CustomerCardService,
    CustomerCardServiceError,
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
        service = CustomerCardService(client)

        try:
            customers = await service.get_recent_customers()
            return service.classify_customers(customers)

        except CustomerCardServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve customers from Maconomy",
            ) from exc
