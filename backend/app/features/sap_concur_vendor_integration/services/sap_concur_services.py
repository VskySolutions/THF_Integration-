import asyncio
import time
from typing import Any, ClassVar

import httpx
from app.core.config import Settings, get_settings


class SAPConcurVendorServiceError(Exception):
    pass


class SAPConcurVendorService:
    _cached_access_token: ClassVar[str | None] = None
    _cached_token_expires_at: ClassVar[float | None] = None
    _token_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    _TOKEN_EXPIRY_MARGIN_SECONDS: ClassVar[float] = 60.0
    _DEFAULT_TOKEN_TTL_SECONDS: ClassVar[float] = 3600.0
    _VENDOR_FIELDS: ClassVar[tuple[str, ...]] = (
        "VendorCode",
        "VendorName",
        "AddressCode",
        "Address1",
        "Address2",
        "City",
        "State",
        "PostalCode",
        "CountryCode",
        "Country",
        "CurrencyCode",
        "TaxID",
        "ContactFirstName",
        "ContactLastName",
        "ContactEmail",
        "ContactPhoneNumber",
        "PaymentMethodType",
        "TaxID"
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    async def _get_token_from_refresh_token(
        self, client: httpx.AsyncClient
    ) -> tuple[str, float]:
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
            raise SAPConcurVendorServiceError(
                "Invalid SAP Concur authentication response"
            ) from exc

        if not isinstance(token, str) or not token:
            raise SAPConcurVendorServiceError(
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

            token, expires_in = await self._get_token_from_refresh_token(client)
            self._cached_access_token = token
            self._cached_token_expires_at = time.time() + expires_in
            return token

    def _invalidate_access_token(self, failed_token: str | None = None) -> None:
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
            self._invalidate_access_token(failed_token=token)
            token = await self._get_valid_access_token(client)
            request_headers["Authorization"] = f"Bearer {token}"
            response = await client.request(
                method, url, headers=request_headers, **kwargs
            )

        return response

    async def get_approved_vendors(self) -> dict[str, Any]:
        url = (
            f"{self.settings.sap_concur_api_base_url}"
            "/api/v3.1/invoice/vendors"
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        params = {
            # "vendorCode": "4029-0",
            "approved": "true", 
            "limit": 999
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await self._request_with_auth(
                    client,
                    "GET",
                    url,
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAPConcurVendorServiceError(
                "SAP Concur vendors request failed"
            ) from exc

        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurVendorServiceError(
                "Invalid SAP Concur vendors response"
            ) from exc
        if not isinstance(payload, dict):
            raise SAPConcurVendorServiceError(
                "Invalid SAP Concur vendors response"
            )

        vendors = payload.get("Vendor")
        if vendors is not None and not isinstance(vendors, list):
            raise SAPConcurVendorServiceError(
                "Invalid SAP Concur vendors response"
            )
        all_vendors = [
            {field: vendor.get(field) for field in self._VENDOR_FIELDS}
            for vendor in (vendors or [])
            if isinstance(vendor, dict)
        ]
        return {"vendors": all_vendors}

    async def get_vendor_by_code(
        self, vendor_code: str
    ) -> dict[str, Any] | None:
        """Fetch one approved vendor from SAP Concur by its vendor code.

        Returns the projected vendor dict, or None when Concur has no
        approved vendor for the code. Mirrors ``get_approved_vendors``
        response handling with the ``vendorCode`` query filter enabled.
        """
        url = (
            f"{self.settings.sap_concur_api_base_url}"
            "/api/v3.1/invoice/vendors"
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        params = {
            "vendorCode": vendor_code.strip(),
            "approved": "true",
            "limit": 999,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await self._request_with_auth(
                    client,
                    "GET",
                    url,
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAPConcurVendorServiceError(
                "SAP Concur vendors request failed"
            ) from exc

        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurVendorServiceError(
                "Invalid SAP Concur vendors response"
            ) from exc
        if not isinstance(payload, dict):
            raise SAPConcurVendorServiceError(
                "Invalid SAP Concur vendors response"
            )

        vendors = payload.get("Vendor")
        if vendors is None:
            return None
        if isinstance(vendors, dict):
            vendors = [vendors]
        if not isinstance(vendors, list):
            raise SAPConcurVendorServiceError(
                "Invalid SAP Concur vendors response"
            )
        for vendor in vendors:
            if not isinstance(vendor, dict):
                continue
            if (
                str(vendor.get("VendorCode") or "").strip()
                == vendor_code.strip()
            ):
                return {
                    field: vendor.get(field)
                    for field in self._VENDOR_FIELDS
                }
        return None
