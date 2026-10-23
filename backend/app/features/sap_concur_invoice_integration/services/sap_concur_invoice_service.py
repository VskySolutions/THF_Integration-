"""Retrieve SAP Concur AP invoice digests and invoice details."""

import asyncio
import time
from typing import Any, ClassVar

import httpx

from app.core.config import Settings, get_settings


class SAPConcurInvoiceServiceError(Exception):
    pass


class SAPConcurInvoiceService:
    # Class-level token cache shared across ALL instances. Required because
    # SAPConcurInvoiceService is instantiated fresh at each call site; an
    # instance-level cache would never be reused. asyncio.Lock + double-check
    # keeps concurrent refreshes safe (Python 3.11 asyncio).
    # (Auth block copied as-is from sap_concur_integration SAPConcurService —
    # Req FR-2.)
    _cached_access_token: ClassVar[str | None] = None
    _cached_token_expires_at: ClassVar[float | None] = None
    _token_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    # Refresh slightly before actual expiry so a token never expires mid-request.
    _TOKEN_EXPIRY_MARGIN_SECONDS: ClassVar[float] = 60.0
    # Fallback TTL when the token response omits expires_in (Concur ~60 min).
    _DEFAULT_TOKEN_TTL_SECONDS: ClassVar[float] = 3600.0

    # Safety ceiling for invoice digest pagination — a well-behaved Concur
    # tenant never approaches this; it only guarantees the paging loop can
    # never run unbounded if a NextPage URL misbehaves.
    _MAX_PAGES: ClassVar[int] = 500

    # Fixed digest search cutoff — product decision (not user input).
    # Concur's real parameter name is camelCase `createDateAfter`
    # (live-verified; `createddateafter` is rejected with 400).
    _DIGEST_CREATE_DATE_AFTER: ClassVar[str] = "2026-10-21"

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
            raise SAPConcurInvoiceServiceError(
                "Invalid SAP Concur authentication response"
            ) from exc

        if not isinstance(token, str) or not token:
            raise SAPConcurInvoiceServiceError(
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
        each call site keeps its existing status handling (404 checks,
        raise_for_status, JSON validation).
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

    # FR-3: GET all invoice digests (fixed `createDateAfter` cutoff, no payload).
    async def get_all_invoice_digests(self) -> list[dict[str, Any]]:
        """Return every payment-request digest created after the fixed cutoff.

        `createDateAfter` is built into the service (no caller input) per
        product decision; Concur requires at least one search parameter and
        rejects `createddateafter` — the real field is camelCase
        `createDateAfter` (live-verified, official swagger). If Concur
        returns a top-level `NextPage` URL it is followed verbatim so the
        complete digest list is retrieved; no additional query parameters
        are ever added by this client. Bounded by `_MAX_PAGES`.
        """
        url = (
            f"{self.settings.sap_concur_api_base_url}"
            "/api/v3.0/invoice/paymentrequestdigests"
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        page_one_params: dict[str, Any] = {
            "createDateAfter": self._DIGEST_CREATE_DATE_AFTER,
        }

        all_items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        next_url: str | None = None
        pages_fetched = 0

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                while True:
                    if pages_fetched >= self._MAX_PAGES:
                        raise SAPConcurInvoiceServiceError(
                            "Concur invoice digest pagination exceeded the "
                            f"maximum page ceiling of {self._MAX_PAGES}"
                        )

                    if next_url is None:
                        request_url = url
                        request_params: dict[str, Any] | None = (
                            page_one_params
                        )
                    else:
                        request_url = next_url
                        request_params = None

                    response = await self._request_with_auth(
                        client,
                        "GET",
                        request_url,
                        headers=headers,
                        params=request_params,
                    )
                    response.raise_for_status()
                    pages_fetched += 1

                    try:
                        payload = response.json()
                    except (TypeError, ValueError) as exc:
                        raise SAPConcurInvoiceServiceError(
                            "Invalid Concur invoice digests response"
                        ) from exc

                    if not isinstance(payload, dict):
                        raise SAPConcurInvoiceServiceError(
                            "Invalid Concur invoice digests response"
                        )

                    # Concur v3.0 list convention: items under "Items".
                    # Live envelope also carries a `PaymentRequestDigest`
                    # array — fall back to it when `Items` is empty.
                    items = payload.get("Items")

                    if items is None or (
                        isinstance(items, list) and not items
                    ):
                        fallback = payload.get("PaymentRequestDigest")
                        if isinstance(fallback, list) and fallback:
                            items = fallback

                    if not isinstance(items, list) or any(
                        not isinstance(item, dict) for item in items
                    ):
                        raise SAPConcurInvoiceServiceError(
                            "Invalid Concur invoice digests response"
                        )

                    # Terminal fallback: an empty page ends pagination
                    # regardless of the NextPage field.
                    if not items:
                        break

                    for item in items:
                        # Official digest schema names the record id
                        # `PaymentRequestId`; tolerate legacy `Id` too.
                        item_id = str(
                            item.get("PaymentRequestId") or item.get("Id") or ""
                        ).strip()

                        if item_id:
                            if item_id in seen_ids:
                                continue
                            seen_ids.add(item_id)

                        all_items.append(item)

                    # Follow the top-level NextPage URL verbatim when present.
                    next_page = payload.get("NextPage")

                    if isinstance(next_page, str):
                        next_page_url = next_page.strip() or None
                    else:
                        next_page_url = None

                    if next_page_url and next_page_url != request_url:
                        next_url = next_page_url
                        continue

                    break

        except httpx.HTTPError as exc:
            raise SAPConcurInvoiceServiceError(
                "SAP Concur invoice digests request failed"
            ) from exc

        print(
            f"[Concur invoice debug] digests complete: {len(all_items)} "
            f"total record(s) across {pages_fetched} page(s)"
        )
        return all_items

    # FR-4: GET invoice detail + line items by Id (no payload).
    async def get_invoice_details(
        self,
        *,
        invoice_id: str,
    ) -> dict[str, Any]:
        """Return one payment request's detail with its line items.

        Returns {"invoice": <detail dict>, "lineItems": <list[dict]>} —
        line items are extracted defensively from `LineItems.LineItem`
        (missing/empty container → empty list; wrong shape → error).
        """
        normalized_invoice_id = str(invoice_id or "").strip()

        if not normalized_invoice_id:
            raise SAPConcurInvoiceServiceError(
                "Invoice ID is required"
            )

        url = (
            f"{self.settings.sap_concur_api_base_url}"
            f"/api/v3.0/invoice/paymentrequest/{normalized_invoice_id}"
        )
        headers = {
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await self._request_with_auth(
                    client,
                    "GET",
                    url,
                    headers=headers,
                )

                if response.status_code == httpx.codes.NOT_FOUND:
                    raise SAPConcurInvoiceServiceError(
                        f"Concur payment request "
                        f"'{normalized_invoice_id}' not found"
                    )

                response.raise_for_status()

        except httpx.HTTPError as exc:
            raise SAPConcurInvoiceServiceError(
                "SAP Concur invoice detail request failed"
            ) from exc

        try:
            invoice = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurInvoiceServiceError(
                "Invalid Concur invoice detail response"
            ) from exc

        if not isinstance(invoice, dict):
            raise SAPConcurInvoiceServiceError(
                "Invalid Concur invoice detail response"
            )

        line_items = self._extract_line_items(invoice)

        return {
            "invoice": invoice,
            "lineItems": line_items,
        }

    @staticmethod
    def _extract_line_items(
        invoice: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Extract `LineItems.LineItem` defensively (Req FR-6)."""
        container = invoice.get("LineItems")

        # Missing container → no line items.
        if container is None:
            return []

        if isinstance(container, list):
            # Tolerate a bare list in place of the wrapper object.
            line_items = container

        elif isinstance(container, dict):
            line_items = container.get("LineItem")

            # Wrapper present but empty → no line items.
            if line_items is None:
                return []

        else:
            raise SAPConcurInvoiceServiceError(
                "Invalid Concur invoice line items response"
            )

        if not isinstance(line_items, list) or any(
            not isinstance(item, dict) for item in line_items
        ):
            raise SAPConcurInvoiceServiceError(
                "Invalid Concur invoice line items response"
            )

        return line_items
