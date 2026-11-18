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
HUBSPOT_BATCH_SIZE = 100
MAX_REQUEST_ATTEMPTS = 3
DEFAULT_RETRY_AFTER_SECONDS = 2.0
MAX_RETRY_AFTER_SECONDS = 60.0


class HubSpotService:
    """Send Company batch upserts and retain confirmed HubSpot IDs."""

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

    async def _upsert_batch(
        self,
        inputs: list[dict[str, Any]],
        batch_number: int,
    ) -> dict[str, Any]:
        headers = self._authorized_headers()
        url = f"{self.settings.hubspot_api_url}{COMPANY_UPSERT_PATH}"

        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                response = await self.client.post(
                    url,
                    headers=headers,
                    json={"inputs": inputs},
                )
            except httpx.HTTPError as exc:
                raise HubSpotError(
                    "HubSpot Company upsert request failed",
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
                    "HubSpot Company upsert was rejected",
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
                    "Invalid HubSpot Company upsert response",
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
                    "Invalid HubSpot Company upsert response",
                    reason="invalid_response",
                    upstream_status=response.status_code,
                    batch_number=batch_number,
                )
            return payload

        raise HubSpotError(
            "HubSpot Company upsert retry limit was reached",
            reason="retry_limit_reached",
            batch_number=batch_number,
        )

    @staticmethod
    def _source_id(result: dict[str, Any]) -> str:
        trace_id = str(result.get("objectWriteTraceId") or "").strip()
        if trace_id.startswith("company-"):
            return trace_id[len("company-") :].strip()
        properties = result.get("properties")
        if isinstance(properties, dict):
            return str(properties.get("maconomy_customer_number") or "").strip()
        return ""

    @staticmethod
    def _batch_error_summary(error: dict[str, Any], batch_number: int) -> dict[str, Any]:
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
                trace_id[len("company-") :]
                if trace_id.startswith("company-")
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
        """Return only Company IDs confirmed in HubSpot batch results."""
        requested_ids = {str(item["id"]) for item in inputs}
        confirmed_ids: dict[str, str] = {}
        batch_errors: list[dict[str, Any]] = []

        for offset in range(0, len(inputs), HUBSPOT_BATCH_SIZE):
            batch_number = offset // HUBSPOT_BATCH_SIZE + 1
            payload = await self._upsert_batch(
                inputs[offset : offset + HUBSPOT_BATCH_SIZE],
                batch_number,
            )
            for result in payload.get("results", []):
                if not isinstance(result, dict):
                    continue
                source_id = self._source_id(result)
                company_id = str(result.get("id") or "").strip()
                if source_id in requested_ids and company_id:
                    confirmed_ids[source_id] = company_id
            for error in payload.get("errors", []):
                if isinstance(error, dict):
                    batch_errors.append(self._batch_error_summary(error, batch_number))

        return {
            "requested": len(inputs),
            "confirmed_ids": confirmed_ids,
            "batch_errors": batch_errors,
        }
