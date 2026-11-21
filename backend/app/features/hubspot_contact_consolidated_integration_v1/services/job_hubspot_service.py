"""HubSpot reads and property updates used only by the jobs extension."""

from typing import Any

from app.features.hubspot_contact_consolidated_integration_v1.exceptions import (
    HubSpotError,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.hubspot_service import (
    HUBSPOT_BATCH_SIZE,
    HubSpotService,
)

CONTACT_SEARCH_PATH = "/crm/objects/2026-09/contacts/search"
CONTACT_UPDATE_PATH = "/crm/objects/2026-09/contacts/batch/update"
COMPANY_UPDATE_PATH = "/crm/objects/2026-09/companies/batch/update"


class JobHubSpotService(HubSpotService):
    async def contacts_for_customer(
        self, customer_number: str
    ) -> list[dict[str, str]]:
        contacts: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        after: str | None = None
        cursors: set[str] = set()
        while True:
            body: dict[str, Any] = {
                "filterGroups": [{"filters": [{
                    "propertyName": "maconomy_customer_number",
                    "operator": "EQ",
                    "value": customer_number,
                }]}],
                "properties": [
                    "maconomy_customer_number",
                    "maconomy__contact_person_number",
                ],
                "limit": 200,
            }
            if after:
                body["after"] = after
            payload = await self._association_request(
                "POST", CONTACT_SEARCH_PATH, body=body
            )
            results = payload.get("results")
            if not isinstance(results, list):
                raise HubSpotError(
                    "HubSpot Contact search returned no results list",
                    reason="invalid_response",
                )
            for item in results:
                if not isinstance(item, dict):
                    continue
                properties = item.get("properties")
                if not isinstance(properties, dict):
                    continue
                if str(properties.get("maconomy_customer_number") or "").strip() != customer_number:
                    continue
                contact_id = str(item.get("id") or "").strip()
                if contact_id and contact_id not in seen_ids:
                    seen_ids.add(contact_id)
                    contacts.append({
                        "hubspot_id": contact_id,
                        "contact_person_number": str(
                            properties.get("maconomy__contact_person_number") or ""
                        ).strip(),
                    })
            paging = payload.get("paging")
            next_page = paging.get("next") if isinstance(paging, dict) else None
            next_after = (
                str(next_page.get("after") or "").strip()
                if isinstance(next_page, dict)
                else ""
            )
            if not next_after:
                break
            if next_after in cursors or len(contacts) >= 10000:
                raise HubSpotError(
                    "HubSpot Contact search pagination could not complete",
                    reason="pagination_failed",
                )
            cursors.add(next_after)
            after = next_after
        return contacts

    async def update_properties_by_id(
        self, object_type: str, properties_by_id: dict[str, dict[str, str]]
    ) -> dict[str, Any]:
        path = (
            COMPANY_UPDATE_PATH if object_type == "company" else CONTACT_UPDATE_PATH
        )
        confirmed_ids: set[str] = set()
        errors: list[dict[str, Any]] = []
        items = list(properties_by_id.items())
        for offset in range(0, len(items), HUBSPOT_BATCH_SIZE):
            batch_number = offset // HUBSPOT_BATCH_SIZE + 1
            chunk = items[offset : offset + HUBSPOT_BATCH_SIZE]
            try:
                payload = await self._upsert_batch(
                    [
                        {
                            "id": hubspot_id,
                            "properties": properties,
                            "objectWriteTraceId": f"job-{object_type}-{hubspot_id}",
                        }
                        for hubspot_id, properties in chunk
                    ],
                    batch_number,
                    path=path,
                    object_label=f"{object_type} CSE and market",
                )
            except HubSpotError as exc:
                errors.append({
                    "batch_number": batch_number,
                    "reason": exc.reason,
                    "upstream_status": exc.upstream_status,
                    "category": exc.category,
                    "correlation_id": exc.correlation_id,
                    "hubspot_ids": [hubspot_id for hubspot_id, _ in chunk],
                })
                continue
            confirmed_ids.update(
                str(item.get("id") or "").strip()
                for item in payload.get("results", [])
                if isinstance(item, dict)
            )
            for error in payload.get("errors", []):
                if isinstance(error, dict):
                    errors.append({
                        **self._batch_error_summary(
                            error, batch_number, f"job-{object_type}-"
                        ),
                        "upstream_status": 207,
                    })
        requested_ids = set(properties_by_id)
        return {
            "requested": len(requested_ids),
            "confirmed_ids": confirmed_ids & requested_ids,
            "failed_ids": requested_ids - confirmed_ids,
            "errors": errors,
        }
