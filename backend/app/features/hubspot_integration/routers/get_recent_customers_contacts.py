from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.features.auth.dependencies import require_api_key
from app.features.hubspot_integration.services.maconomy_service import MaconomyService


router = APIRouter(
    prefix="/hubspot",
    tags=["hubspot-integration"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "/customers-contacts/recent",
    response_model=list[dict[str, Any]],
)
async def get_recent_customers_contacts() -> list[dict[str, Any]]:
    try:
        return await MaconomyService().get_customers_with_contact_persons()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch customers and contact persons from Maconomy: {str(exc)}",
        ) from exc