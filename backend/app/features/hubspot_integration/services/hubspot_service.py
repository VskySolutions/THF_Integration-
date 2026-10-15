"""HubSpot CRM service: service-key auth, upserts."""

import asyncio
from typing import Any

import httpx

from app.core.config import Settings, get_settings


MAX_REQUEST_ATTEMPTS = 3
DEFAULT_RETRY_AFTER_SECONDS = 2.0
MAX_RETRY_AFTER_SECONDS = 60.0
COMPANY_UPSERT_PATH = "/crm/objects/2026-09/companies/batch/upsert"
CONTACT_UPSERT_PATH = "/crm/objects/2026-09/contacts/batch/upsert"


class HubSpotServiceError(Exception):
    """Raised when a HubSpot API request fails."""


class HubSpotAuthError(HubSpotServiceError):
    """Raised when HubSpot rejects the service key (e.g. HTTP 401)."""


class HubSpotConfigError(HubSpotServiceError):
    """Raised when the HubSpot service key is missing or empty in settings."""


class HubSpotService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()

    def _authorized_headers(self) -> dict[str, str]:
        """Static Bearer header from the HubSpot service key (Private App token)."""
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
        """Send an authorized request; handles 429 backoff.

        Auth is a static ``Authorization: Bearer <HUBSPOT_SERVICE_KEY>``
        header - there is no token generation. A 401 is a config/scope
        problem with the service key and is surfaced immediately.
        """
        attempts = 0

        while True:
            attempts += 1
            print(f"[HubSpot] {method} {path} (attempt {attempts})")
            try:
                response = await self.client.request(
                    method,
                    self._url(path),
                    headers=self._authorized_headers(),
                    json=json_body,
                )
            except httpx.HTTPError as exc:
                print(f"[HubSpot] request error: {exc!r}")
                raise HubSpotServiceError(
                    "HubSpot request failed"
                ) from exc

            print(
                f"[HubSpot] <- {response.status_code} "
                f"{response.text}"
            )

            if response.status_code in (200, 207):
                try:
                    return response.status_code, response.json()
                except ValueError as exc:
                    raise HubSpotServiceError(
                        "Invalid HubSpot response payload"
                    ) from exc

            if response.status_code == 401:
                print(
                    "[HubSpot] 401 rejected service key - check "
                    "HUBSPOT_SERVICE_KEY and private app scopes"
                )
                raise HubSpotAuthError(
                    "HubSpot rejected the service key (HTTP 401) - "
                    "check HUBSPOT_SERVICE_KEY and the private app scopes"
                    f"{self._response_error_suffix(response)}"
                )

            if (
                response.status_code == 429
                and attempts < MAX_REQUEST_ATTEMPTS
            ):
                delay = self._retry_after_seconds(response)
                print(
                    f"[HubSpot] 429 rate-limited; retrying after "
                    f"{delay}s (attempt {attempts}/{MAX_REQUEST_ATTEMPTS})"
                )
                await asyncio.sleep(delay)
                continue

            print(f"[HubSpot] failing status {response.status_code}")
            raise HubSpotServiceError(
                f"HubSpot request failed with HTTP "
                f"{response.status_code}"
                f"{self._response_error_suffix(response)}"
            )

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        raw = response.headers.get("Retry-After")
        try:
            if raw is None:
                return DEFAULT_RETRY_AFTER_SECONDS
            return min(
                float(raw),
                MAX_RETRY_AFTER_SECONDS,
            )
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

    async def upsert_companies(
        self,
        companies: dict[str, Any],
    ) -> dict[str, Any]:
        """Upsert HubSpot Companies.

        Accepts the prepared payload dict (``{"inputs": [...]}`` from
        ``map_customers_company()``) and POSTs it as-is.
        """
        status_code, payload = await self._request(
            method="POST",
            path=COMPANY_UPSERT_PATH,
            json_body=companies,
        )
        inputs = companies.get("inputs", [])
        return {
            "requested": len(inputs) if isinstance(inputs, list) else 0,
            "status": status_code,
            "result": payload,
        }

    async def upsert_contacts(
        self,
        contacts: dict[str, Any],
    ) -> dict[str, Any]:
        """Upsert HubSpot Contacts.

        Accepts the prepared payload dict (``{"inputs": [...]}`` from
        ``map_contacts_hb_contacts()``) and POSTs it as-is.
        """
        status_code, payload = await self._request(
            method="POST",
            path=CONTACT_UPSERT_PATH,
            json_body=contacts,
        )
        inputs = contacts.get("inputs", [])
        return {
            "requested": len(inputs) if isinstance(inputs, list) else 0,
            "status": status_code,
            "result": payload,
        }
