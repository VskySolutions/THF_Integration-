"""Upsert Maconomy customers as HubSpot Companies in batches."""

import asyncio
import math
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.features.hubspot_contact_consolidated_integration_v1.exceptions import (
    HubSpotError,
)

COMPANY_UPSERT_PATH = "/crm/objects/2026-09/companies/batch/upsert"
CONTACT_UPSERT_PATH = "/crm/objects/2026-09/contacts/batch/upsert"
COMPANY_BATCH_READ_PATH = "/crm/objects/2026-09/companies/batch/read"
CONTACT_BATCH_READ_PATH = "/crm/objects/2026-09/contacts/batch/read"
ASSOCIATION_BATCH_READ_PATH = "/crm/associations/2026-09/contacts/companies/batch/read"
HUBSPOT_BATCH_SIZE = 100
MAX_REQUEST_ATTEMPTS = 3
DEFAULT_RETRY_AFTER_SECONDS = 2.0
MAX_RETRY_AFTER_SECONDS = 60.0


class HubSpotService:
    """Send Company or Contact batch upserts and retain confirmed IDs."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()

    def _authorized_headers(self) -> dict[str, str]:
        service_key = self.settings.hubspot_service_key.get_secret_value().strip()
        if not service_key:
            raise HubSpotError(
                "HubSpot service key is not configured",
                reason="missing_service_key",
            )
        return {
            "Authorization": f"Bearer {service_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        value = response.headers.get("Retry-After")
        try:
            seconds = float(value) if value is not None else DEFAULT_RETRY_AFTER_SECONDS
        except ValueError:
            seconds = DEFAULT_RETRY_AFTER_SECONDS
        if not math.isfinite(seconds):
            seconds = DEFAULT_RETRY_AFTER_SECONDS
        return max(0.0, min(seconds, MAX_RETRY_AFTER_SECONDS))

    @staticmethod
    def _error_context(response: httpx.Response) -> dict[str, str | None]:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            payload = {}
        category = str(payload.get("category") or "").strip() or None
        correlation_id = str(
            payload.get("correlationId")
            or response.headers.get("X-HubSpot-Correlation-Id")
            or ""
        ).strip() or None
        message = str(payload.get("message") or "").strip()[:1000] or None
        return {
            "category": category,
            "correlation_id": correlation_id,
            "upstream_message": message,
        }

    async def _association_request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        unassociated_contact_ids: set[str] | None = None,
        allow_missing_objects: bool = False,
    ) -> Any:
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                response = await self.client.request(
                    method,
                    f"{self.settings.hubspot_api_url}{path}",
                    headers=self._authorized_headers(),
                    json=body,
                )
            except httpx.HTTPError as exc:
                raise HubSpotError(
                    f"HubSpot {method} request failed for {path}",
                    reason=(
                        "timeout"
                        if isinstance(exc, httpx.TimeoutException)
                        else "request_error"
                    ),
                ) from exc
            if response.status_code == 429 and attempt < MAX_REQUEST_ATTEMPTS:
                await asyncio.sleep(self._retry_after_seconds(response))
                continue
            if response.status_code not in (200, 201, 204, 207):
                raise HubSpotError(
                    f"HubSpot {method} request was rejected for {path}",
                    reason=(
                        "authentication_failed"
                        if response.status_code == 401
                        else "rate_limited"
                        if response.status_code == 429
                        else "http_status"
                    ),
                    upstream_status=response.status_code,
                    **self._error_context(response),
                )
            if not response.content:
                return {}
            try:
                payload = response.json()
            except ValueError as exc:
                raise HubSpotError(
                    f"Invalid HubSpot {method} response for {path}",
                    reason="invalid_json",
                    upstream_status=response.status_code,
                ) from exc
            raw_errors = payload.get("errors") if isinstance(payload, dict) else None
            if (
                allow_missing_objects
                and response.status_code == 207
                and isinstance(raw_errors, list)
                and raw_errors
                and all(
                    isinstance(error, dict)
                    and str(
                        error.get("category") or payload.get("category") or ""
                    ).strip() == "OBJECT_NOT_FOUND"
                    for error in raw_errors
                )
            ):
                payload.setdefault("results", [])
                return payload
            if isinstance(raw_errors, list) and unassociated_contact_ids is not None:
                # HubSpot reports an unlinked Contact as a 207 batch read error.

                def is_unassociated_contact(error: Any) -> bool:
                    if not isinstance(error, dict):
                        return False
                    category = str(
                        error.get("category") or payload.get("category") or ""
                    ).strip()
                    message = str(error.get("message") or "").strip()
                    prefix = "No company is associated with contact "
                    return (
                        category == "OBJECT_NOT_FOUND"
                        and message.startswith(prefix)
                        and message.endswith(".")
                        and message[len(prefix) : -1] in unassociated_contact_ids
                    )

                other_errors = [
                    error for error in raw_errors if not is_unassociated_contact(error)
                ]
                if len(other_errors) < len(raw_errors) and not other_errors:
                    payload.setdefault("results", [])
                    return payload
                raw_errors = other_errors
            if not isinstance(payload, dict) or raw_errors:
                first_error = (
                    raw_errors[0]
                    if isinstance(raw_errors, list)
                    and raw_errors
                    and isinstance(raw_errors[0], dict)
                    else {}
                )
                raise HubSpotError(
                    f"HubSpot {method} returned an incomplete response for {path}",
                    reason="partial_response",
                    upstream_status=response.status_code,
                    category=(
                        str(
                            first_error.get("category")
                            or payload.get("category")
                            or ""
                        ).strip()
                        or None
                        if isinstance(payload, dict)
                        else None
                    ),
                    correlation_id=(
                        str(
                            first_error.get("correlationId")
                            or payload.get("correlationId")
                            or ""
                        ).strip()
                        or None
                        if isinstance(payload, dict)
                        else None
                    ),
                    upstream_message=(
                        str(
                            first_error.get("message")
                            or payload.get("message")
                            or ""
                        ).strip()[:1000]
                        or None
                        if isinstance(payload, dict)
                        else None
                    ),
                )
            return payload
        raise HubSpotError(
            f"HubSpot {method} retry limit was reached for {path}",
            reason="retry_limit_reached",
        )

    async def _lookup_ids(
        self, numbers: set[str], *, path: str, property_name: str
    ) -> dict[str, str]:
        found: dict[str, str] = {}
        ordered = sorted(numbers)
        for offset in range(0, len(ordered), HUBSPOT_BATCH_SIZE):
            try:
                payload = await self._association_request(
                    "POST",
                    path,
                    allow_missing_objects=True,
                    body={
                        "idProperty": property_name,
                        "properties": [property_name],
                        "inputs": [
                            {"id": number}
                            for number in ordered[offset : offset + HUBSPOT_BATCH_SIZE]
                        ],
                    },
                )
            except HubSpotError as exc:
                if exc.upstream_status == 404 and exc.category == "OBJECT_NOT_FOUND":
                    continue
                raise
            results = payload.get("results")
            if not isinstance(results, list):
                raise HubSpotError(
                    f"HubSpot batch read returned no results list for {path}",
                    reason="invalid_response",
                )
            for item in results:
                if not isinstance(item, dict):
                    continue
                properties = item.get("properties")
                number = (
                    str(properties.get(property_name) or "").strip()
                    if isinstance(properties, dict)
                    else ""
                )
                hubspot_id = str(item.get("id") or "").strip()
                if number in numbers and hubspot_id:
                    found[number] = hubspot_id
        return found

    async def lookup_companies(self, numbers: set[str]) -> dict[str, str]:
        return await self._lookup_ids(
            numbers, path=COMPANY_BATCH_READ_PATH, property_name="maconomy_customer_number"
        )

    async def lookup_contacts(self, numbers: set[str]) -> dict[str, str]:
        found = await self._lookup_ids(
            numbers, path=CONTACT_BATCH_READ_PATH, property_name="maconomy__contact_person_number"
        )
        missing = numbers - set(found)
        if missing:
            found.update(
                await self._lookup_ids(
                    missing,
                    path=CONTACT_BATCH_READ_PATH,
                    property_name="maconomy_contact_person_number",
                )
            )
        return found

    async def read_contact_company_associations(
        self, contact_ids: set[str]
    ) -> dict[str, set[str]]:
        found = {contact_id: set() for contact_id in contact_ids}
        ordered = sorted(contact_ids)
        for offset in range(0, len(ordered), HUBSPOT_BATCH_SIZE):
            chunk = ordered[offset : offset + HUBSPOT_BATCH_SIZE]
            payload = await self._association_request(
                "POST",
                ASSOCIATION_BATCH_READ_PATH,
                body={
                    "inputs": [{"id": contact_id} for contact_id in chunk]
                },
                unassociated_contact_ids=set(chunk),
            )
            results = payload.get("results")
            if not isinstance(results, list):
                raise HubSpotError(
                    "HubSpot Contact-Company association read returned no results list",
                    reason="invalid_response",
                )
            for item in results:
                if not isinstance(item, dict):
                    continue
                source = item.get("from")
                contact_id = (
                    str(source.get("id") or "").strip()
                    if isinstance(source, dict)
                    else ""
                )
                targets = item.get("to")
                if contact_id not in found or not isinstance(targets, list):
                    continue
                found[contact_id].update(
                    str(target.get("toObjectId") or "").strip()
                    for target in targets
                    if isinstance(target, dict) and target.get("toObjectId")
                )
        return found

    async def associate_contact_to_company(
        self, contact_id: str, company_id: str
    ) -> None:
        await self._association_request(
            "PUT",
            f"/crm/objects/2026-09/contacts/{contact_id}/associations/default/companies/{company_id}",
        )

    async def _upsert_batch(
        self,
        inputs: list[dict[str, Any]],
        batch_number: int,
        *,
        path: str,
        object_label: str,
    ) -> dict[str, Any]:
        headers = self._authorized_headers()
        url = f"{self.settings.hubspot_api_url}{path}"

        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                response = await self.client.post(
                    url,
                    headers=headers,
                    json={"inputs": inputs},
                )
            except httpx.HTTPError as exc:
                raise HubSpotError(
                    f"HubSpot {object_label} upsert request failed",
                    reason=(
                        "timeout"
                        if isinstance(exc, httpx.TimeoutException)
                        else "request_error"
                    ),
                    batch_number=batch_number,
                ) from exc

            if response.status_code == 429 and attempt < MAX_REQUEST_ATTEMPTS:
                await asyncio.sleep(self._retry_after_seconds(response))
                continue

            if response.status_code not in (200, 201, 207):
                context = self._error_context(response)
                raise HubSpotError(
                    f"HubSpot {object_label} upsert was rejected",
                    reason=(
                        "authentication_failed"
                        if response.status_code == 401
                        else "rate_limited"
                        if response.status_code == 429
                        else "http_status"
                    ),
                    upstream_status=response.status_code,
                    batch_number=batch_number,
                    **context,
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise HubSpotError(
                    f"Invalid HubSpot {object_label} upsert response",
                    reason="invalid_json",
                    upstream_status=response.status_code,
                    batch_number=batch_number,
                ) from exc
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("results", []), list)
                or not isinstance(payload.get("errors", []), list)
            ):
                raise HubSpotError(
                    f"Invalid HubSpot {object_label} upsert response",
                    reason="invalid_response",
                    upstream_status=response.status_code,
                    batch_number=batch_number,
                )
            return payload

        raise HubSpotError(
            f"HubSpot {object_label} upsert retry limit was reached",
            reason="retry_limit_reached",
            batch_number=batch_number,
        )

    @staticmethod
    def _source_id(
        result: dict[str, Any], trace_prefix: str, property_name: str
    ) -> str:
        trace_id = str(result.get("objectWriteTraceId") or "").strip()
        if trace_id.startswith(trace_prefix):
            return trace_id[len(trace_prefix) :].strip()
        properties = result.get("properties")
        if isinstance(properties, dict):
            return str(properties.get(property_name) or "").strip()
        return ""

    @staticmethod
    def _batch_error_summary(
        error: dict[str, Any], batch_number: int, trace_prefix: str
    ) -> dict[str, Any]:
        context = error.get("context")
        trace_id = str(error.get("objectWriteTraceId") or "").strip()
        if not trace_id and isinstance(context, dict):
            trace_values = context.get("objectWriteTraceId")
            if isinstance(trace_values, list) and trace_values:
                trace_id = str(trace_values[0]).strip()
        details: list[dict[str, Any]] = []
        raw_details = error.get("errors")
        if isinstance(raw_details, list):
            for detail in raw_details[:10]:
                if not isinstance(detail, dict):
                    continue
                detail_context = detail.get("context")
                property_names = (
                    detail_context.get("propertyName")
                    if isinstance(detail_context, dict)
                    else None
                )
                details.append(
                    {
                        "code": str(detail.get("code") or "").strip() or None,
                        "property_names": (
                            [str(name) for name in property_names]
                            if isinstance(property_names, list)
                            else None
                        ),
                        "message": str(detail.get("message") or "").strip()[:1000]
                        or None,
                    }
                )
        return {
            "batch_number": batch_number,
            "source_id": (
                trace_id[len(trace_prefix) :]
                if trace_id.startswith(trace_prefix)
                else None
            ),
            "category": str(error.get("category") or "").strip() or None,
            "sub_category": str(error.get("subCategory") or "").strip() or None,
            "correlation_id": str(error.get("correlationId") or "").strip() or None,
            "message": str(error.get("message") or "").strip()[:1000] or None,
            "details": details,
        }

    async def upsert_companies(
        self,
        inputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._upsert_objects(
            inputs,
            path=COMPANY_UPSERT_PATH,
            object_label="Company",
            trace_prefix="company-",
            property_name="maconomy_customer_number",
        )

    async def upsert_contacts(
        self,
        inputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._upsert_objects(
            inputs,
            path=CONTACT_UPSERT_PATH,
            object_label="Contact",
            trace_prefix="contact-",
            property_name="maconomy__contact_person_number",
        )

    async def _upsert_objects(
        self,
        inputs: list[dict[str, Any]],
        *,
        path: str,
        object_label: str,
        trace_prefix: str,
        property_name: str,
    ) -> dict[str, Any]:
        """Return only object IDs confirmed in HubSpot batch results."""
        requested_ids = {str(item["id"]) for item in inputs}
        confirmed_ids: dict[str, str] = {}
        batch_errors: list[dict[str, Any]] = []

        for offset in range(0, len(inputs), HUBSPOT_BATCH_SIZE):
            batch_number = offset // HUBSPOT_BATCH_SIZE + 1
            payload = await self._upsert_batch(
                inputs[offset : offset + HUBSPOT_BATCH_SIZE],
                batch_number,
                path=path,
                object_label=object_label,
            )
            for result in payload.get("results", []):
                if not isinstance(result, dict):
                    continue
                source_id = self._source_id(result, trace_prefix, property_name)
                object_id = str(result.get("id") or "").strip()
                if source_id in requested_ids and object_id:
                    confirmed_ids[source_id] = object_id
            for error in payload.get("errors", []):
                if isinstance(error, dict):
                    batch_errors.append(
                        self._batch_error_summary(error, batch_number, trace_prefix)
                    )

        return {
            "requested": len(inputs),
            "confirmed_ids": confirmed_ids,
            "batch_errors": batch_errors,
        }
