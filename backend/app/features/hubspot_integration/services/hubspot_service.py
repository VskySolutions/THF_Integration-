"""HubSpot CRM service: authentication, upserts, lookups, and associations."""

import asyncio
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings


MAX_REQUEST_ATTEMPTS = 3
DEFAULT_RETRY_AFTER_SECONDS = 2.0
MAX_RETRY_AFTER_SECONDS = 60.0
HUBSPOT_BATCH_SIZE = 100

COMPANY_UPSERT_PATH = "/crm/objects/2026-09/companies/batch/upsert"
COMPANY_BATCH_READ_PATH = "/crm/objects/2026-09/companies/batch/read"
CONTACT_UPSERT_PATH = "/crm/objects/2026-09/contacts/batch/upsert"


class HubSpotServiceError(Exception):
    """Raised when a HubSpot API request fails."""


class HubSpotAuthError(HubSpotServiceError):
    """Raised when HubSpot rejects the configured service key."""


class HubSpotConfigError(HubSpotServiceError):
    """Raised when the HubSpot service key is missing."""


class HubSpotService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()

    def _authorized_headers(self) -> dict[str, str]:
        key = self.settings.hubspot_service_key.get_secret_value().strip()
        if not key:
            raise HubSpotConfigError("HUBSPOT_SERVICE_KEY is not configured")
        return {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.settings.hubspot_api_url}{path}"

    async def _request(
        self,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        attempts = 0

        while True:
            attempts += 1
            try:
                response = await self.client.request(
                    method,
                    self._url(path),
                    headers=self._authorized_headers(),
                    json=json_body,
                )
            except httpx.HTTPError as exc:
                raise HubSpotServiceError("HubSpot request failed") from exc

            if response.status_code in (200, 201, 204, 207):
                if response.status_code == 204 or not response.content:
                    return response.status_code, {}
                try:
                    return response.status_code, response.json()
                except ValueError as exc:
                    raise HubSpotServiceError(
                        "Invalid HubSpot response payload"
                    ) from exc

            if response.status_code == 401:
                raise HubSpotAuthError(
                    "HubSpot rejected the service key (HTTP 401) - "
                    "check HUBSPOT_SERVICE_KEY and the private app scopes"
                    f"{self._response_error_suffix(response)}"
                )

            if response.status_code == 429 and attempts < MAX_REQUEST_ATTEMPTS:
                await asyncio.sleep(self._retry_after_seconds(response))
                continue

            raise HubSpotServiceError(
                f"HubSpot request failed with HTTP {response.status_code}"
                f"{self._response_error_suffix(response)}"
            )

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        raw = response.headers.get("Retry-After")
        try:
            if raw is None:
                return DEFAULT_RETRY_AFTER_SECONDS
            return min(float(raw), MAX_RETRY_AFTER_SECONDS)
        except ValueError:
            return DEFAULT_RETRY_AFTER_SECONDS

    @staticmethod
    def _response_error_suffix(response: httpx.Response) -> str:
        message = HubSpotService._response_error_message(response)
        return f": {message}" if message else ""

    @staticmethod
    def _response_error_message(response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        message = payload.get("message")
        category = payload.get("category")
        parts = []
        if isinstance(message, str) and message.strip():
            parts.append(message.strip())
        if isinstance(category, str) and category.strip():
            parts.append(f"category={category.strip()}")
        return "; ".join(parts) if parts else None

    async def _batch_upsert(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        raw_inputs = payload.get("inputs", [])
        inputs = raw_inputs if isinstance(raw_inputs, list) else []
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        statuses: list[int] = []

        for offset in range(0, len(inputs), HUBSPOT_BATCH_SIZE):
            chunk = inputs[offset : offset + HUBSPOT_BATCH_SIZE]
            status_code, response_payload = await self._request(
                method="POST",
                path=path,
                json_body={"inputs": chunk},
            )
            statuses.append(status_code)
            if isinstance(response_payload, dict):
                response_results = response_payload.get("results", [])
                response_errors = response_payload.get("errors", [])
                if isinstance(response_results, list):
                    results.extend(
                        item
                        for item in response_results
                        if isinstance(item, dict)
                    )
                if isinstance(response_errors, list):
                    errors.extend(
                        item
                        for item in response_errors
                        if isinstance(item, dict)
                    )

        return {
            "requested": len(inputs),
            "status": 207 if 207 in statuses or errors else 200,
            "result": {
                "results": results,
                "errors": errors,
            },
        }

    async def upsert_companies(
        self,
        companies: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._batch_upsert(COMPANY_UPSERT_PATH, companies)

    async def upsert_contacts(
        self,
        contacts: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._batch_upsert(CONTACT_UPSERT_PATH, contacts)

    async def lookup_companies(
        self,
        customer_numbers: list[str],
    ) -> dict[str, str]:
        """Resolve Maconomy customer numbers to HubSpot Company IDs."""
        company_ids: dict[str, str] = {}
        unique_numbers = list(dict.fromkeys(customer_numbers))

        for offset in range(0, len(unique_numbers), HUBSPOT_BATCH_SIZE):
            chunk = unique_numbers[offset : offset + HUBSPOT_BATCH_SIZE]
            _, payload = await self._request(
                method="POST",
                path=COMPANY_BATCH_READ_PATH,
                json_body={
                    "idProperty": "maconomy_customer_number",
                    "properties": ["maconomy_customer_number"],
                    "inputs": [{"id": number} for number in chunk],
                },
            )
            if not isinstance(payload, dict):
                continue
            results = payload.get("results", [])
            if not isinstance(results, list):
                continue
            for result in results:
                if not isinstance(result, dict):
                    continue
                properties = result.get("properties", {})
                if not isinstance(properties, dict):
                    continue
                customer_number = str(
                    properties.get("maconomy_customer_number") or ""
                ).strip()
                company_id = str(result.get("id") or "").strip()
                if customer_number and company_id:
                    company_ids[customer_number] = company_id

        return company_ids

    async def associate_contact_to_company(
        self,
        contact_id: str,
        company_id: str,
    ) -> None:
        """Create or preserve the default Contact-to-Company association."""
        contact = quote(str(contact_id), safe="")
        company = quote(str(company_id), safe="")
        await self._request(
            method="PUT",
            path=(
                f"/crm/v4/objects/contacts/{contact}/associations/"
                f"default/companies/{company}"
            ),
        )

    @staticmethod
    def index_results_by_source_id(
        operation_result: dict[str, Any] | None,
        *,
        property_name: str,
        trace_prefix: str,
    ) -> dict[str, str]:
        """Map a successful upsert result to source ID and HubSpot object ID."""
        indexed: dict[str, str] = {}
        if not operation_result:
            return indexed
        payload = operation_result.get("result", {})
        if not isinstance(payload, dict):
            return indexed
        results = payload.get("results", [])
        if not isinstance(results, list):
            return indexed

        for result in results:
            if not isinstance(result, dict):
                continue
            hubspot_id = str(result.get("id") or "").strip()
            trace_id = str(result.get("objectWriteTraceId") or "").strip()
            properties = result.get("properties", {})
            source_id = ""
            if trace_id.startswith(trace_prefix):
                source_id = trace_id[len(trace_prefix) :].strip()
            elif isinstance(properties, dict):
                source_id = str(properties.get(property_name) or "").strip()
            if source_id and hubspot_id:
                indexed[source_id] = hubspot_id
        return indexed
