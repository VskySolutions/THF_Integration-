
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
            print("[Sync] 1/4 Fetching recent Maonomy customers...")
            customers = await maconomy.get_recent_customers()
            print(f"[Sync] 1/4 Fetched {len(customers)} customers")
        except CustomerCardServiceError as exc:
            print(f"[Sync] 1/4 Maonomy fetch FAILED: {exc}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve customers from Maconomy",
            ) from exc

        classified = maconomy.classify_customers(customers)
        create_list = classified["create"]
        update_list = classified["update"]
        print(
            f"[Sync] 2/4 Classified: create={len(create_list)} "
            f"update={len(update_list)} skip={len(classified['skip'])}"
        )

        try:
            # 1) Company upsert from the dynamic payload.
            company_payload = map_customers_to_company_upsert(
                create_list, update_list
            )
            print(
                f"[Sync] 3/4 Company payload: "
                f"inputs={len(company_payload['inputs'])} "
                f"skipped={len(company_payload['skipped'])}"
            )

            companies_result = None
            if company_payload["inputs"]:
                companies_result = await hubspot.upsert_companies(
                    {"inputs": company_payload["inputs"]}
                )
                print("companies_result:", companies_result)
                print(
                    f"[Sync] 3/4 Companies: "
                    f"requested={companies_result.get('requested')} "
                    f"status={companies_result.get('status')}"
                )
            else:
                print(
                    "[Sync] 3/4 No company inputs to upsert - "
                    "skipping API call"
                )

            # 2) Contact upsert from the dynamic payload.
            contact_payload = map_customers_to_contact_upsert(
                create_list, update_list
            )
            print(
                f"[Sync] 4/4 Contact payload: "
                f"inputs={len(contact_payload['inputs'])} "
                f"skipped={len(contact_payload['skipped'])}"
            )

            contacts_result = None
            if contact_payload["inputs"]:
                contacts_result = await hubspot.upsert_contacts(
                    {"inputs": contact_payload["inputs"]}
                )
                print("contacts_result:", contacts_result)
                print(
                    f"[Sync] 4/4 Contacts: "
                    f"requested={contacts_result.get('requested')} "
                    f"status={contacts_result.get('status')}"
                )
            else:
                print(
                    "[Sync] 4/4 No contact inputs to upsert - "
                    "skipping API call"
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
            "classification": {
                "create": len(create_list),
                "update": len(update_list),
                "skip": len(classified["skip"]),
            },
            "companies_skipped": len(company_payload["skipped"]),
            "contacts_skipped": len(contact_payload["skipped"]),
            "companies": companies_result,
            "contacts": contacts_result,
        }
