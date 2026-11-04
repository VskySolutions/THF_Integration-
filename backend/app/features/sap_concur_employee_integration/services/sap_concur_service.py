"""Create SAP Concur users from mapped Maconomy employees.

Uses the SCIM Bulk endpoint. Each HTTP request carries multiple ``POST
/Users`` operations (one per employee) so a batch is created in one call.
Authentication mirrors ``sap_concur_integration/services/sap_concur_service.py``.
"""

import asyncio
import time
from typing import Any, ClassVar

import httpx

from app.core.config import Settings, get_settings
from app.features.sap_concur_employee_integration.mappers.employee_mapper import (
    BULK_MAX_OPERATIONS,
    build_bulk_operations,
    build_bulk_request,
)

SCIM_CONTENT_TYPE = "application/scim+json"
TOKEN_CONTENT_TYPE = "application/x-www-form-urlencoded"
BULK_PATH = "/profile/v4/Bulk/"
TOKEN_PATH = "/oauth2/v0/token"


class SAPConcurEmployeeServiceError(Exception):
    """Raised when SAP Concur employee creation fails."""


class SAPConcurEmployeeService:
    """Create SAP Concur users from Maconomy employee records."""

    # Class-level cache shared by every instance (the service is instantiated
    # per call site). Lock + double-check keeps concurrent refreshes safe.
    _cached_access_token: ClassVar[str | None] = None
    _cached_token_expires_at: ClassVar[float | None] = None
    _token_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    _TOKEN_EXPIRY_MARGIN_SECONDS: ClassVar[float] = 60.0
    _DEFAULT_TOKEN_TTL_SECONDS: ClassVar[float] = 3600.0

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self.timeout = 60.0

    async def create_employees(
        self,
        employees: list[dict[str, Any]],
        *,
        batch_size: int = BULK_MAX_OPERATIONS,
    ) -> dict[str, Any]:
        """Create many SAP Concur users, batching operations per request.

        Returns an aggregate with ``created``, ``failed``, ``skipped``,
        ``requests_sent`` and per-``bulkId`` ``details``.
        """
        operations, skipped = build_bulk_operations(employees)

        if not operations:
            return {
                "created": 0,
                "failed": 0,
                "skipped": skipped,
                "requests_sent": 0,
                "details": [],
            }

        try:
            if self.client is not None:
                (
                    created,
                    failed,
                    requests_sent,
                    details,
                ) = await self._create_operations(
                    self.client,
                    operations,
                    batch_size,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    (
                        created,
                        failed,
                        requests_sent,
                        details,
                    ) = await self._create_operations(
                        client,
                        operations,
                        batch_size,
                    )
        except httpx.HTTPError as exc:
            raise SAPConcurEmployeeServiceError(
                "SAP Concur bulk creation failed"
            ) from exc

        return {
            "created": created,
            "failed": failed,
            "skipped": skipped,
            "requests_sent": requests_sent,
            "details": details,
        }

    async def create_employee(
        self,
        employee: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a single SAP Concur user."""
        return await self.create_employees([employee])

    async def _create_operations(
        self,
        client: httpx.AsyncClient,
        operations: list[dict[str, Any]],
        batch_size: int,
    ) -> tuple[int, int, int, list[dict[str, Any]]]:
        """Send Bulk requests and aggregate per-operation results."""
        created = 0
        failed = 0
        requests_sent = 0
        details: list[dict[str, Any]] = []
        effective_batch_size = max(1, batch_size)

        for start in range(0, len(operations), effective_batch_size):
            batch = operations[start : start + effective_batch_size]
            payload = build_bulk_request(batch)

            response = await self._request_with_auth(
                client,
                "POST",
                self._bulk_url(),
                headers=self._scim_headers(),
                json=payload,
            )
            response.raise_for_status()

            results = self._parse_bulk_response(response)
            requests_sent += 1

            for result in results:
                if result["success"]:
                    created += 1
                else:
                    failed += 1
                details.append(result)

        return created, failed, requests_sent, details

    @staticmethod
    def _parse_bulk_response(
        response: httpx.Response,
    ) -> list[dict[str, Any]]:
        """Validate a SCIM BulkResponse and normalise operation results."""
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurEmployeeServiceError(
                "Invalid SAP Concur bulk response"
            ) from exc

        if not isinstance(payload, dict):
            raise SAPConcurEmployeeServiceError(
                "Invalid SAP Concur bulk response"
            )

        operations = payload.get("Operations")
        if not isinstance(operations, list) or any(
            not isinstance(operation, dict)
            for operation in operations
        ):
            raise SAPConcurEmployeeServiceError(
                "Invalid SAP Concur bulk response"
            )

        results: list[dict[str, Any]] = []
        for operation in operations:
            status = SAPConcurEmployeeService._coerce_status(
                operation.get("status")
            )
            success = status in (200, 201)

            detail: Any = None
            if not success:
                detail = (
                    operation.get("response")
                    or operation.get("message")
                    or operation.get("detail")
                )

            results.append(
                {
                    "bulkId": operation.get("bulkId"),
                    "status": status,
                    "success": success,
                    "detail": detail,
                }
            )

        return results

    @staticmethod
    def _coerce_status(value: Any) -> int | None:
        """Return an integer HTTP status, or None when not parseable."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.isdigit():
                return int(text)
        return None

    async def _get_token_from_refresh_token(
        self,
        client: httpx.AsyncClient,
    ) -> tuple[str, float]:
        """Fetch a fresh access token from SAP Concur."""
        response = await client.post(
            f"{self._base_url()}{TOKEN_PATH}",
            headers={"Content-Type": TOKEN_CONTENT_TYPE},
            data={
                "client_id": (
                    self.settings.sap_concur_client_id.get_secret_value()
                ),
                "client_secret": (
                    self.settings.sap_concur_client_secret.get_secret_value()
                ),
                "grant_type": "refresh_token",
                "refresh_token": (
                    self.settings.sap_concur_refresh_token.get_secret_value()
                ),
            },
        )
        response.raise_for_status()

        try:
            payload = response.json()
            token = payload["access_token"]
        except (KeyError, TypeError, ValueError) as exc:
            raise SAPConcurEmployeeServiceError(
                "Invalid SAP Concur authentication response"
            ) from exc

        if not isinstance(token, str) or not token:
            raise SAPConcurEmployeeServiceError(
                "Invalid SAP Concur authentication response"
            )

        try:
            expires_in = float(
                payload.get(
                    "expires_in",
                    self._DEFAULT_TOKEN_TTL_SECONDS,
                )
            )
        except (TypeError, ValueError):
            expires_in = self._DEFAULT_TOKEN_TTL_SECONDS
        if expires_in <= 0:
            expires_in = self._DEFAULT_TOKEN_TTL_SECONDS

        return token, expires_in

    async def _get_valid_access_token(
        self,
        client: httpx.AsyncClient,
    ) -> str:
        """Return a cached access token while it is still valid."""
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
            now = time.time()
            token = self._cached_access_token
            expires_at = self._cached_token_expires_at
            if (
                token
                and expires_at is not None
                and now < expires_at - self._TOKEN_EXPIRY_MARGIN_SECONDS
            ):
                return token

            token, expires_in = await self._get_token_from_refresh_token(
                client
            )
            self._cached_access_token = token
            self._cached_token_expires_at = time.time() + expires_in
            return token

    def _invalidate_access_token(
        self,
        failed_token: str | None = None,
    ) -> None:
        """Clear the cached token when it still matches the failed token."""
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
        """Send an authenticated request, refreshing once on 401/403."""
        request_headers = dict(headers or {})
        token = await self._get_valid_access_token(client)
        request_headers["Authorization"] = f"Bearer {token}"

        response = await client.request(
            method,
            url,
            headers=request_headers,
            **kwargs,
        )

        if response.status_code in (
            httpx.codes.UNAUTHORIZED,
            httpx.codes.FORBIDDEN,
        ):
            self._invalidate_access_token(failed_token=token)
            token = await self._get_valid_access_token(client)
            request_headers["Authorization"] = f"Bearer {token}"
            response = await client.request(
                method,
                url,
                headers=request_headers,
                **kwargs,
            )

        return response

    def _base_url(self) -> str:
        return str(self.settings.sap_concur_api_base_url).rstrip("/")

    def _bulk_url(self) -> str:
        return f"{self._base_url()}{BULK_PATH}"

    @staticmethod
    def _scim_headers() -> dict[str, str]:
        return {
            "Content-Type": SCIM_CONTENT_TYPE,
            "Accept": SCIM_CONTENT_TYPE,
        }
