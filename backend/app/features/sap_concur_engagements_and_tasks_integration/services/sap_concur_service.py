"""Create SAP Concur engagement/task list items via the bulk list endpoint.

Concur validates the bulk ``requests`` array to 1-250 entries, so payloads
above that limit are split into sequential chunks; the per-chunk responses
are aggregated back into a single SUCCESS / PARTIAL_SUCCESS result.
"""

import asyncio
import time
from typing import Any, ClassVar

import httpx
from app.core.config import Settings, get_settings
from app.features.sap_concur_engagements_and_tasks_integration.constants import (
    CONCUR_BULK_MAX_REQUESTS,
)


class SAPConcurEngagementTaskServiceError(Exception):
    pass


_SUCCESS_STATUS = "SUCCESS"
_PARTIAL_STATUS = "PARTIAL_SUCCESS"


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
        posted to ``/list/v4/lists/{listid}/bulk``. Concur validates the
        ``requests`` array to 1-250 entries, so larger payloads are split
        into sequential chunks of at most ``CONCUR_BULK_MAX_REQUESTS``.

        A single chunk is posted once and its response is returned
        verbatim (identical to the pre-chunking behaviour). Multiple
        chunks are posted sequentially over one HTTP client and their
        outcomes are aggregated into a single result: ``SUCCESS`` only
        when every chunk succeeded with ``SUCCESS``, otherwise
        ``PARTIAL_SUCCESS`` carrying the merged per-item ``errors``
        (Concur's own errors plus synthesized entries for items in
        failed chunks). Only when every chunk fails does this raise
        ``SAPConcurEngagementTaskServiceError``.
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

        chunks = [
            requests[index : index + CONCUR_BULK_MAX_REQUESTS]
            for index in range(0, len(requests), CONCUR_BULK_MAX_REQUESTS)
        ]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if len(chunks) == 1:
                result = await self._post_bulk_chunk(
                    client, url, chunks[0], headers
                )
                print(
                    f"Concur bulk chunk 1/1 ({len(chunks[0])} requests): "
                    f"{result.get('status')}"
                )
                return result

            good: list[dict[str, Any]] = []
            bad: list[tuple[list[dict[str, Any]], str]] = []
            for index, chunk in enumerate(chunks, start=1):
                try:
                    result = await self._post_bulk_chunk(
                        client, url, chunk, headers
                    )
                except SAPConcurEngagementTaskServiceError as exc:
                    # Keep going: the remaining chunks are independent and
                    # are still worth attempting (items are retried on the
                    # next run via the mapping table).
                    print(
                        f"Concur bulk chunk {index}/{len(chunks)} "
                        f"({len(chunk)} requests) failed: {exc}"
                    )
                    bad.append((chunk, str(exc)))
                    continue
                status = str(result.get("status") or "")
                print(
                    f"Concur bulk chunk {index}/{len(chunks)} "
                    f"({len(chunk)} requests): {status or 'UNKNOWN'}"
                )
                if status in (_SUCCESS_STATUS, _PARTIAL_STATUS):
                    good.append(result)
                else:
                    bad.append(
                        (
                            chunk,
                            f"bulk request status {status or 'UNKNOWN'}",
                        )
                    )

        return self._aggregate_chunk_results(good, bad, len(chunks))

    async def _post_bulk_chunk(
        self,
        client: httpx.AsyncClient,
        url: str,
        chunk: list[dict[str, Any]],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """POST one <=250-item chunk to the Concur bulk endpoint."""
        try:
            response = await self._request_with_auth(
                client,
                "POST",
                url,
                headers=headers,
                json={"requests": chunk},
            )
            print(
                f"Concur bulk list response: {response.status_code} "
                f"{response.text}"
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SAPConcurEngagementTaskServiceError(
                "SAP Concur bulk list request failed: "
                f"{exc.response.status_code} {exc.response.text[:500]}"
            ) from exc
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

    @staticmethod
    def _aggregate_chunk_results(
        good: list[dict[str, Any]],
        bad: list[tuple[list[dict[str, Any]], str]],
        chunk_count: int,
    ) -> dict[str, Any]:
        """Merge per-chunk outcomes into one Concur-shaped result.

        ``good`` holds parsed chunk bodies whose status is SUCCESS or
        PARTIAL_SUCCESS; ``bad`` holds (chunk requests, reason) pairs for
        chunks that failed at HTTP/parse level or returned an unexpected
        status. Items of ``bad`` chunks become synthesized error entries
        (Concur's ``listItem`` shape) so the router attributes FAILED
        logs to exactly those engagements/tasks.
        """
        if not good:
            reasons = "; ".join(
                dict.fromkeys(reason for _, reason in bad)
            )
            raise SAPConcurEngagementTaskServiceError(
                f"All {chunk_count} SAP Concur bulk chunks failed: {reasons}"
            )

        errors: list[dict[str, Any]] = []
        for result in good:
            for error in result.get("errors") or []:
                if isinstance(error, dict):
                    errors.append(error)

        for chunk, reason in bad:
            for item in chunk:
                if not isinstance(item, dict):
                    continue
                short_code = str(item.get("shortCode") or "").strip()
                if not short_code:
                    continue
                list_item: dict[str, str] = {"shortCode": short_code}
                parent_code = str(item.get("parentCode") or "").strip()
                if parent_code:
                    list_item["parentCode"] = parent_code
                errors.append(
                    {
                        "id": "chunk.failed",
                        "message": reason,
                        "listItem": list_item,
                    }
                )

        partial = bool(bad) or any(
            str(result.get("status") or "") != _SUCCESS_STATUS
            for result in good
        )
        return {
            "status": _PARTIAL_STATUS if partial else _SUCCESS_STATUS,
            "errors": errors,
            "chunk_count": chunk_count,
        }
