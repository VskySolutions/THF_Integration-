from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, ClassVar, TypeVar

import asyncio
import time

import httpx

from app.core.config import Settings, get_settings

T = TypeVar("T")


class SAPConcurServiceError(Exception):
    pass


class SAPConcurEntityCreationError(SAPConcurServiceError):
    def __init__(self, message: str, *, reconciliation_allowed: bool) -> None:
        super().__init__(message)
        self.reconciliation_allowed = reconciliation_allowed


class SAPConcurService:
    # Class-level token cache shared across ALL instances. Required because
    # SAPConcurService is instantiated fresh at each call site; an
    # instance-level cache would never be reused. asyncio.Lock + double-check
    # keeps concurrent refreshes safe (Python 3.11 asyncio).
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


    #  Get report details using report_id V4 API
    async def get_report_by_id(
        self,
        report_id: str,
        user_id: str,
        context_type: str,
    ) -> dict[str, Any] | None:
        print(f"Fetching report details for report_id: {report_id}, user_id: {user_id}, context_type: {context_type}")
        if not report_id.strip():
            raise SAPConcurServiceError("Invalid Concur Expense report ID")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await self._request_with_auth(
                    client,
                    "GET",
                    f"{self.settings.sap_concur_api_base_url}/expensereports/v4/users/{user_id}/context/{context_type}/reports/{report_id}",
                    headers={
                        "Content-Type": "application/json",
                    },
                )
                if response.status_code == httpx.codes.NOT_FOUND:
                    return None
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError(
                "Unable to reconcile report in Concur"
            ) from exc

        try:
            report = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid Concur report response"
            ) from exc

        if not isinstance(report, dict):
            raise SAPConcurServiceError(
                "Invalid Concur report response"
            )

        exp_report_id = report["reportId"]
        report_name = report["name"]
        if (
            not isinstance(exp_report_id, str)
            or not exp_report_id.strip()
            or not isinstance(report_name, str)
        ):
            raise SAPConcurServiceError(
                "Invalid Concur report response"
            )

        return report


    # Get expenses aligned with the report
    async def get_expenses_by_report_id(
        self,
        report_id: str,
        user_id: str,
        context_type: str,
    ) -> list[dict[str, Any]]:
        if not report_id.strip():
            raise SAPConcurServiceError("Invalid Concur report ID")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await self._request_with_auth(
                    client,
                    "GET",
                    f"{self.settings.sap_concur_api_base_url}/expensereports/v4/users/{user_id}/context/{context_type}/reports/{report_id}/expenses",
                    headers={
                        "Content-Type": "application/json",
                    },
                )
                if response.status_code == httpx.codes.NOT_FOUND:
                    raise SAPConcurServiceError(
                        f"Concur report '{report_id}' not found"
                    )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError(
                "Unable to retrieve expenses from Concur"
            ) from exc

        try:
            expenses = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid Concur expenses response"
            ) from exc

        if not isinstance(expenses, list) or any(
            not isinstance(expense, dict) for expense in expenses
        ):
            raise SAPConcurServiceError(
                "Invalid Concur expenses response"
            )

        for expense in expenses:
            expense_id = expense.get("expenseId")
            # amount = expense.get("Amount")
            if (
                not isinstance(expense_id, str)
                or not expense_id.strip()
                # or not isinstance(amount, (int, float))
                # or isinstance(amount, bool)
            ):
                raise SAPConcurServiceError(
                    "Invalid Concur expenses response"
                )

        return expenses


    # Get detailed expense data by expense_id (includes customData)
    async def get_expenses_by_expense_id(
        self,
        expense_id: str,
        report_id: str,
        user_id: str,
        context_type: str,
    ) -> dict[str, Any] | None:
        """
        Retrieve complete detailed expense data for a specific expense by expense_id.
        
        This endpoint returns ALL expense details including:
        - All standard expense fields (expenseType, transactionDate, amount, etc.)
        - customData array with custom1, custom2, custom5, custom6
        
        This data should be used for:
        - Expense mapping to Maconomy format
        - Custom data processing (Location, Department, Travel Reason, Client Engagement)
        
        Args:
            expense_id: The unique identifier for the expense
            report_id: The report ID containing this expense
            user_id: The SAP Concur user ID
            context_type: The context type (e.g., "TRAVELER")
            
        Returns:
            Complete detailed expense dict, or None if not found
        """
        print(f"Fetching detailed expense data for expense_id: {expense_id}, report_id: {report_id}")
        if not expense_id.strip():
            raise SAPConcurServiceError("Invalid expense ID")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await self._request_with_auth(
                    client,
                    "GET",
                    f"{self.settings.sap_concur_api_base_url}/expensereports/v4/users/{user_id}/context/{context_type}/reports/{report_id}/expenses/{expense_id}",
                    headers={
                        "Content-Type": "application/json",
                    },
                )
                if response.status_code == httpx.codes.NOT_FOUND:
                    return None
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError(
                "Unable to retrieve detailed expense from Concur"
            ) from exc

        try:
            expense = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid Concur expense response"
            ) from exc

        if not isinstance(expense, dict):
            raise SAPConcurServiceError(
                "Invalid Concur expense response"
            )

        return expense


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
                "grant_type" : "refresh_token",
                "refresh_token": self.settings.sap_concur_refresh_token.get_secret_value(),
            },
            # data = f"client_id={self.settings.sap_concur_client_id}&client_secret={self.settings.sap_concur_client_secret.get_secret_value()}&grant_type=refresh_token&refresh_token={self.settings.sap_concur_refresh_token}"
        )
        
        response.raise_for_status()

        try:
            payload = response.json()
            token = payload["access_token"]
            new_refresh_token = payload["refresh_token"]
            # print(f"Concur Access Token: {token}")
            # print(f"Concur Refresh Token: {new_refresh_token}")
        except (KeyError, TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid SAP Concur authentication response"
            ) from exc

        if not isinstance(token, str) or not token:
            raise SAPConcurServiceError(
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
        print("Yes")
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


    # Safety ceiling for report pagination (NFR-1). A well-behaved Concur
    # tenant never approaches this; it exists only to guarantee the paging loop
    # can never run unbounded if the top-level NextPage URL misbehaves.
    _MAX_REPORT_PAGES: ClassVar[int] = 500

    def _validate_report_items(self, items: Any) -> list[dict[str, Any]]:
        """Validate one page of Concur expense-report items (FR-11).

        Shared by the batch and retry report-retrieval paths. Preserves the
        original exception type and message so integration behaviour is
        unchanged.
        """
        if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items
        ):
            raise SAPConcurServiceError(
                "Invalid Concur expense reports response"
            )

        for item in items:
            create_date = item.get("CreateDate")
            if not isinstance(create_date, str) or not create_date:
                raise SAPConcurServiceError(
                    "Invalid Concur expense reports response"
                )

        return items

    @staticmethod
    def _extract_next_url(metadata_next: Any) -> str | None:
        """Return the next-page URL from a Concur top-level `NextPage` value, if any.

        Concur returns `NextPage` at the response root as an absolute next-page
        URL with its own paging (offset/page/etc.) already encoded. We follow
        that URL verbatim rather than constructing an `offset` ourselves, so
        paging works regardless of the exact param style Concur expects. Returns
        None when `NextPage` is absent/empty (caller treats that as the terminal
        page). OQ-3.
        """
        if not isinstance(metadata_next, str):
            return None
        text = metadata_next.strip()
        return text or None

    async def _retry_once(
        self,
        factory: Callable[[], Awaitable[T]],
        *,
        retry_on: tuple[type[BaseException], ...],
    ) -> T:
        """Run `factory` once; on a matching failure, retry exactly once.

        Bounded to 2 attempts (initial + one immediate retry), with no sleep or
        backoff (FR-8). If the second attempt also raises, that exception is
        re-raised with the original chained via `from` (NFR-2). A clean success
        is never re-issued, and a failure the caller has already handled
        internally is never seen here (FR-10).
        """
        try:
            return await factory()
        except retry_on:
            return await factory()

    async def _fetch_report_page(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        page_params: dict[str, Any],
    ) -> httpx.Response:
        """Issue one authenticated report page request and enforce 2xx.

        A non-2xx is printed (status + body) before `raise_for_status` converts
        it to `httpx.HTTPError`, so the real Concur failure is visible in the
        terminal instead of surfacing as the generic "SAP Concur request failed".
        """
        response = await self._request_with_auth(
            client, "GET", url, headers=headers, params=page_params
        )

        response.raise_for_status()
        return response

    async def _get_all_expense_reports_paged(
        self,
        client: httpx.AsyncClient,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Retrieve every Concur report matching `params`, paging past limit=100.

        Page 1 sends the original params with NO `offset` (this Concur edition
        rejects a caller-supplied offset on the first request). Subsequent pages
        follow the absolute URL Concur returns in the top-level `NextPage` verbatim,
        so paging works regardless of the exact param style Concur expects.
        Pagination stops when `NextPage` is null/absent or a page returns no
        `Items`. Each individual page request is retried at most once on a
        genuine transport failure (FR-7/FR-8) — a clean success is never
        re-issued, and the internal 401/403 token-refresh inside
        `_request_with_auth` stays orthogonal (FR-10). Bounded by
        `_MAX_REPORT_PAGES` (NFR-1).
        """
        url = f"{self.settings.sap_concur_api_base_url}/api/v3.0/expense/reports"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        # Page 1 uses the original, proven-working params (NO offset): this
        # Concur edition rejects a caller-supplied `offset` on the first
        # request ("Invalid offset"), so paging is driven by the URL Concur
        # returns in the top-level NextPage instead.
        all_items: list[dict[str, Any]] = []
        seen_report_ids: set[str] = set()
        next_url: str | None = None
        next_params: dict[str, Any] | None = None
        pages_fetched = 0

        while True:
            if pages_fetched >= self._MAX_REPORT_PAGES:
                raise SAPConcurServiceError(
                    "Concur expense report pagination exceeded the "
                    f"maximum page ceiling of {self._MAX_REPORT_PAGES}"
                )

            if next_url is None:
                request_url = url
                request_params: dict[str, Any] | None = params
            else:
                request_url = next_url
                request_params = next_params

            # Per-page single retry (FR-7/FR-8): exactly one immediate
            # re-attempt, only when the request genuinely fails (transport
            # error or a non-2xx that survived the 401/403 token-refresh).
            async def _fetch_page() -> httpx.Response:
                return await self._fetch_report_page(
                    client, request_url, headers, request_params
                )

            response = await self._retry_once(
                _fetch_page,
                retry_on=(httpx.HTTPError,),
            )

            pages_fetched += 1

            try:
                payload = response.json()
                items = payload["Items"]
            except (KeyError, TypeError, ValueError) as exc:
                raise SAPConcurServiceError(
                    "Invalid Concur expense reports response"
                ) from exc

            # TESTING: report this page's record count.
            print(
                f"[Concur debug] page {pages_fetched}: {len(items)} record(s)"
            )

            if not isinstance(items, list) or any(
                not isinstance(item, dict) for item in items
            ):
                raise SAPConcurServiceError(
                    "Invalid Concur expense reports response"
                )

            # Terminal fallback: an empty page ends pagination regardless of
            # the NextPage field, so a missing/odd NextPage can never loop forever.
            if not items:
                break

            for item in items:
                report_id = str(item.get("ReportId") or "").strip()
                if report_id:
                    if report_id in seen_report_ids:
                        continue
                    seen_report_ids.add(report_id)
                all_items.append(item)

            # Confirmed live (2026-10-14): the next-page URL is exposed as a
            # TOP-LEVEL `NextPage` field (a URL string when more pages exist,
            # null on the last page) — NOT under `Metadata`. This endpoint
            # rejects client-driven `offset`.
            metadata_next = payload.get("NextPage")


            next_page_url = self._extract_next_url(metadata_next)


            # Preferred: follow the next-page URL Concur returns verbatim.
            if next_page_url and next_page_url != request_url:
                
                next_url = next_page_url
                next_params = None
                continue

            # TESTING: explain why pagination is stopping on this page.
            if not next_page_url:
                stop_reason = "next URL is None (no followable NextPage)"
            else:
                stop_reason = "next URL == request_url (guard stop)"

            break

        # Validate the accumulated set exactly as the previous single-page
        # paths did (same exception type/message — FR-11).
        # TESTING: report the total retrieved count to verify paging past 100.
        print(
            f"[Concur debug] pagination complete: {len(all_items)} total report(s) "
            f"across {pages_fetched} page(s) (beyond 100: {len(all_items) > 100})"
        )
        return self._validate_report_items(all_items)

    # Get yesterday and today's new expense reports from SAP Concur
    async def get_yesterday_and_todays_new_expense_reports_from_sap_concur(
        self,
    ) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await self._get_new_expense_reports(
                    client,
                )
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError(f"SAP Concur request failed: {exc!r}") from exc


    async def _get_new_expense_reports(
        self,
        client: httpx.AsyncClient,
    ) -> list[dict[str, Any]]:
        """
        Fetch Concur expense reports created yesterday or today.
        """
        print("Fetching new expense reports from SAP Concur...")
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)

        print(f"Fetching reports from {yesterday} to {tomorrow}")
        params = {
            "user": "rajlaxmi.mandavkar@thf-cpa.com.uat",
            "modifiedDateAfter": yesterday.isoformat(),
            "modifiedDateBefore": tomorrow.isoformat(),
            # "approvalStatusCode": "A_APPR",
            # "paymentStatusCode": "P_PROC",
            "limit": 100,
        }

        return await self._get_all_expense_reports_paged(client, params)

    # Retry API
    # Get approved expense reports from SAP Concur for retry processing
    async def get_retry_candidate_expense_reports_from_sap_concur(
        self,
    ) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await self._get_retry_candidate_expense_reports(
                    client,
                )
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError(f"SAP Concur request failed: {exc!r}") from exc


    async def _get_retry_candidate_expense_reports(
        self,
        client: httpx.AsyncClient,
    ) -> list[dict[str, Any]]:
        """
        Fetch Concur expense reports with approvalStatusCode=A_APPR.

        No date window (retry must reach older failed reports — OQ1).
        Pages past limit=100 so no matching report is missed (FR-2).
        """
        params = {
            "user": "ALL",
            "approvalStatusCode": "A_APPR",
            "limit": 100,
        }

        return await self._get_all_expense_reports_paged(client, params)


    # Get expense reports by email ID from SAP Concur
    async def get_expense_reports_by_email_id_from_sap_concur(
        self,
        email_id: str,
    ) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await self._get_expense_reports_by_email_id(
                    client,
                    email_id,
                )
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError("SAP Concur request failed") from exc


    async def _get_expense_reports_by_email_id(
        self,
        client: httpx.AsyncClient,
        email_id: str,
    ) -> list[dict[str, Any]]:
        """
        Fetch Concur expense reports for a specific user by Email ID.
        """
        print(f"Fetching expense reports for email_id: {email_id}")

        print(f"Fetching reports for user: {email_id}")
        url = f"{self.settings.sap_concur_api_base_url}/api/v3.0/expense/reports"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        params = {
            "user": email_id,
            "limit": 100,
        }

        response = await self._request_with_auth(
            client, "GET", url, headers=headers, params=params
        )
        response.raise_for_status()

        try:
            payload = response.json()
            items = payload["Items"]
        except (KeyError, TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid Concur expense reports response"
            ) from exc

        if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items
        ):
            raise SAPConcurServiceError(
                "Invalid Concur expense reports response"
            )

        return items


    async def get_user_id_by_login_id(self, owner_login_id: str) -> str:
        try:
            print(f"Fetching user ID for owner_login_id: {owner_login_id}")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                url = f"{self.settings.sap_concur_api_base_url}/profile/identity/v4/Users"
                headers = {
                    "Accept": "application/json",
                }
                params = {
                    "filter": f'userName eq "{owner_login_id}"',
                }

                response = await self._request_with_auth(
                    client, "GET", url, headers=headers, params=params
                )
                # print("Response:", response)
                response.raise_for_status()

                try:
                    payload = response.json()
                    user_id = payload["Resources"][0].get("id")
                except (KeyError, TypeError, ValueError, IndexError) as exc:
                    raise SAPConcurServiceError(
                        "Invalid SAP Concur user response"
                    ) from exc
                except ValueError as exc:
                    raise SAPConcurServiceError(
                        "Invalid SAP Concur user response"
                    ) from exc


                return user_id
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError("SAP Concur request failed") from exc


    # Retrieve List items - Custom data (Department, Location, Travel reason, client engagement)
    async def get_list_items_by_id(
        self,
        report_id: str,
        user_id: str,
        context_type: str,
        item_id: str
    ) -> dict[str, Any] | None:
        print(f"========= get_list_items_by_id ========")
        if not report_id.strip():
            raise SAPConcurServiceError("Invalid Concur Expense report ID")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await self._request_with_auth(
                    client,
                    "GET",
                    f"{self.settings.sap_concur_api_base_url}/list/v4/items?id={item_id}",
                    headers={
                        "Content-Type": "application/json",
                    },
                )
                if response.status_code == httpx.codes.NOT_FOUND:
                    return None
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError(
                "Unable to reconcile list item in Concur"
            ) from exc

        try:
            items = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid Concur list item response"
            ) from exc

        if not isinstance(items, list):
            raise SAPConcurServiceError(
                "Invalid Concur list item response"
            )

        item = items[0]
        code = item["code"]
        short_code = item["shortCode"]
        value = item["value"]
        if (
            not isinstance(code, str)
            or not isinstance(short_code, str)
            or not isinstance(value, str)
        ):
            raise SAPConcurServiceError(
                "Invalid Concur report response"
            )

        return {
            "code": code,
            "short_code": short_code,
            "value": value
        }