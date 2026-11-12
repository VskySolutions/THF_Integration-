"""Create SAP Concur engagement/task list items via the bulk list endpoint."""

import asyncio
import time
from typing import Any, ClassVar

import httpx
from app.core.config import Settings, get_settings


class SAPConcurEngagementTaskServiceError(Exception):
    pass


class SAPConcurEngagementTaskService:
    # Class-level token cache shared across ALL instances. Required because
    # the service is instantiated fresh at each call site; an instance-level
    # cache would never be reused. asyncio.Lock + double-check keeps
    # concurrent refreshes safe (Python 3.11 asyncio).
    # (Auth block copied as-is from sap_concur_invoice_integration
    # SAPConcurInvoiceService.)
    _cached_access_token: ClassVar[str | None] = None
    _cached_token_expires_at: ClassVar[float | None] = None
    _token_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    # Refresh slightly before actual expiry so a token never expires mid-request.
    _TOKEN_EXPIRY_MARGIN_SECONDS: ClassVar[float] = 60.0
    # Fallback TTL when the token response omits expires_in (Concur ~60 min).
    _DEFAULT_TOKEN_TTL_SECONDS: ClassVar[float] = 3600.0

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    # Get Token from Concur API
    async def _get_token_from_refresh_token(
        self, client: httpx.AsyncClient
    ) -> tuple[str, float]:
        """Fetch a fresh access token from Concur.

        Returns:
            (access_token, expires_in_seconds) — expires_in falls back to
            _DEFAULT_TOKEN_TTL_SECONDS when the response omits it.
        """

        response = await client.post(
            f"{self.settings.sap_concur_api_base_url}/oauth2/v0/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": self.settings.sap_concur_client_id.get_secret_value(),
                "client_secret": (
                    self.settings.sap_concur_client_secret.get_secret_value()
                ),
                "grant_type": "refresh_token",
                "refresh_token": self.settings.sap_concur_refresh_token.get_secret_value(),
            },
        )

        response.raise_for_status()

        try:
            payload = response.json()
            token = payload["access_token"]
        except (KeyError, TypeError, ValueError) as exc:
            raise SAPConcurEngagementTaskServiceError(
                "Invalid SAP Concur authentication response"
            ) from exc

        if not isinstance(token, str) or not token:
            raise SAPConcurEngagementTaskServiceError(
                "Invalid SAP Concur authentication response"
            )

        try:
            expires_in = float(payload.get("expires_in", self._DEFAULT_TOKEN_TTL_SECONDS))
        except (TypeError, ValueError):
            expires_in = self._DEFAULT_TOKEN_TTL_SECONDS
        if expires_in <= 0:
            expires_in = self._DEFAULT_TOKEN_TTL_SECONDS

        return token, expires_in

    async def _get_valid_access_token(self, client: httpx.AsyncClient) -> str:
        """Return a cached SAP Concur access token while still valid.

        Token is generated only when required:
        - no token cached, or
        - cached token within the 60s safety margin of expiry, or
        - cache invalidated after a 401/403 response.

        Async-safe: lock-free fast path (no await between check and return),
        slow path serialized via class-level asyncio.Lock with double-check.
        """

        now = time.time()
        token = self._cached_access_token
        expires_at = self._cached_token_expires_at
        if (
            token
            and expires_at is not None
            and now < expires_at - self._TOKEN_EXPIRY_MARGIN_SECONDS
        ):
            return token

        async with self._token_lock:
            # Double-check: another coroutine may have refreshed while waiting.
            now = time.time()
            token = self._cached_access_token
            expires_at = self._cached_token_expires_at
            if (
                token
                and expires_at is not None
                and now < expires_at - self._TOKEN_EXPIRY_MARGIN_SECONDS
            ):
                return token

            # On fetch failure nothing is cached; existing error propagates.
            token, expires_in = await self._get_token_from_refresh_token(client)
            self._cached_access_token = token
            self._cached_token_expires_at = time.time() + expires_in
            print(
                f"Concur access token cached; expires in {expires_in:.0f}s"
            )
            return token

    def _invalidate_access_token(self, failed_token: str | None = None) -> None:
        """Clear the cached token, optionally only if it still matches the
        token that just failed (avoids wiping a token another coroutine
        already refreshed)."""
        if failed_token is None or self._cached_access_token == failed_token:
            self._cached_access_token = None
            self._cached_token_expires_at = None

    async def _request_with_auth(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an authenticated request using the reusable access token.

        On 401/403: invalidate the cached token, obtain a fresh one, and
        retry exactly once. The (possibly retried) response is returned so
        each call site keeps its existing status handling.
        """
        request_headers = dict(headers or {})
        token = await self._get_valid_access_token(client)
        request_headers["Authorization"] = f"Bearer {token}"
        response = await client.request(
            method, url, headers=request_headers, **kwargs
        )

        if response.status_code in (
            httpx.codes.UNAUTHORIZED,
            httpx.codes.FORBIDDEN,
        ):
            print(
                f"Concur token rejected ({response.status_code}); "
                "refreshing token and retrying once"
            )
            self._invalidate_access_token(failed_token=token)
            token = await self._get_valid_access_token(client)
            request_headers["Authorization"] = f"Bearer {token}"
            response = await client.request(
                method, url, headers=request_headers, **kwargs
            )

        return response

    async def create_engagements_and_tasks(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Bulk-create engagement (parent) and task (child) list items.

        ``payload`` is the mapper's output (``{"requests": [...]}``) and is
        posted verbatim to ``/list/v4/lists/{listid}/bulk``. The Concur
        response (SUCCESS / PARTIAL_SUCCESS) is returned as-is.
        """
        list_id = (self.settings.sap_engagement_list_id or "").strip()
        if not list_id:
            raise SAPConcurEngagementTaskServiceError(
                "SAP Concur engagement list id is not configured "
                "(sap_engagement_list_id)"
            )

        requests = payload.get("requests") if isinstance(payload, dict) else None
        if not isinstance(requests, list) or not requests:
            raise SAPConcurEngagementTaskServiceError(
                "No engagement/task records to create"
            )

        url = (
            f"{self.settings.sap_concur_api_base_url}"
            f"/list/v4/lists/{list_id}/bulk"
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Language": "en",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await self._request_with_auth(
                    client,
                    "POST",
                    url,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAPConcurEngagementTaskServiceError(
                "SAP Concur bulk list request failed"
            ) from exc

        try:
            result = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurEngagementTaskServiceError(
                "Invalid SAP Concur bulk list response"
            ) from exc

        if not isinstance(result, dict):
            raise SAPConcurEngagementTaskServiceError(
                "Invalid SAP Concur bulk list response"
            )

        return result
