
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from app.features.auth.dependencies import require_api_key
from app.features.hubspot_integration.mappers.company_mapper import (
    map_customers_company,
)
from app.features.hubspot_integration.mappers.contact_mapper import (
    map_contacts_hb_contacts,
)
from app.features.hubspot_integration.services.hubspot_service import (
    HubSpotService,
    HubSpotServiceError,
)
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


@router.post("/sync/customers")
async def sync_customers_to_hubspot() -> dict[str, Any]:
    """Fetch recent Maconomy customers; upsert Companies & Contacts."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        maconomy = CustomerCardService(client)
        hubspot = HubSpotService(client)

        try:
            print("[Sync] 1/3 Fetching recent Maonomy customers...")
            customers = await maconomy.get_recent_customers()
            print(f"[Sync] 1/3 Fetched {len(customers)} customers")
        except CustomerCardServiceError as exc:
            print(f"[Sync] 1/3 Maonomy fetch FAILED: {exc}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve customers from Maconomy",
            ) from exc

        try:
            # 1) Company upsert from the verified static payload.
            print("[Sync] 2/3 Upserting companies (static payload)...")
            companies_result = await hubspot.upsert_companies(
                map_customers_company()
            )
            print("companies_result:", companies_result)
            print(
                f"[Sync] 2/3 Companies: "
                f"requested={companies_result.get('requested')} "
                f"status={companies_result.get('status')}"
            )

            # 2) Contact upsert from the verified static payload.
            print("[Sync] 3/3 Upserting contacts (static payload)...")
            contacts_result = await hubspot.upsert_contacts(
                map_contacts_hb_contacts()
            )
            print("contacts_result:", contacts_result)
            print(
                f"[Sync] 3/3 Contacts: "
                f"requested={contacts_result.get('requested')} "
                f"status={contacts_result.get('status')}"
            )
        except HubSpotServiceError as exc:
            print(f"[Sync] HubSpot step FAILED: {exc}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to complete HubSpot sync",
            ) from exc

        print("[Sync] Done - returning summary")
        return {
            "customers_fetched": len(customers),
            "companies": companies_result,
            "contacts": contacts_result,
        }
