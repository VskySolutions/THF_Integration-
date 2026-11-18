"""Authenticate with Maconomy and read recently changed customer cards."""

import asyncio
import base64
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.features.hubspot_contact_consolidated_integration_v1.constants import (
    CUSTOMER_CARD_FIELDS,
    CUSTOMER_NUMBER_FIELD,
    CUSTOMER_SYNCED_VERSION_FIELD,
    SYNC_WINDOW_DAYS,
    VERSION_FIELD,
)
from app.features.hubspot_contact_consolidated_integration_v1.exceptions import (
    MaconomyError,
)

AUTH_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.authentication+json; charset=utf-8; version=3.0"
)
CONTAINER_ACCEPT = (
    "application/vnd.deltek.maconomy.containers+json; charset=utf-8; version=9.0"
)
CONTAINER_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.containers+json; charset=UTF-8; version=9.0"
)
ACTIVE_CUSTOMERS_RESTRICTION_TEMPLATE = (
    "(ActiveStatus = ActiveType'Active) and "
    "(createddate>={window_start} or changeddate>={window_start})"
)


class MaconomyService:
    """Cache one X-Reconnect token for all calls made during a bulk run."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self._reconnect_token: str | None = None
        self._auth_lock = asyncio.Lock()

    async def authenticate(self) -> str:
        if self._reconnect_token is not None:
            return self._reconnect_token

        async with self._auth_lock:
            if self._reconnect_token is not None:
                return self._reconnect_token

            shortname = quote(self.settings.maconomy_shortname, safe="")
            url = f"{self.settings.maconomy_url}/maconomy-api/auth/{shortname}/login"
            credentials = (
                f"{self.settings.maconomy_username}:"
                f"{self.settings.maconomy_password.get_secret_value()}"
            )
            encoded_credentials = base64.b64encode(
                credentials.encode("utf-8")
            ).decode("ascii")
            try:
                response = await self.client.get(
                    url,
                    headers={
                        "Accept": AUTH_CONTENT_TYPE,
                        "Maconomy-Authentication": "X-Reconnect",
                        "Authorization": f"Basic {encoded_credentials}",
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise MaconomyError(
                    "Maconomy authentication failed",
                    stage="authentication",
                    reason=(
                        "http_status"
                        if isinstance(exc, httpx.HTTPStatusError)
                        else "request_error"
                    ),
                    upstream_status=(
                        exc.response.status_code
                        if isinstance(exc, httpx.HTTPStatusError)
                        else None
                    ),
                ) from exc

            token = response.headers.get("Maconomy-Reconnect", "").strip()
            if response.status_code != 204:
                raise MaconomyError(
                    "Maconomy authentication failed",
                    stage="authentication",
                    reason="unexpected_status",
                    upstream_status=response.status_code,
                )
            if not token:
                raise MaconomyError(
                    "Maconomy authentication failed",
                    stage="authentication",
                    reason="missing_reconnect_token",
                    upstream_status=response.status_code,
                )

            self._reconnect_token = token
            return token

    async def discover_customers(self) -> list[dict[str, Any]]:
        """Read active customer cards created or changed since yesterday."""
        reconnect_token = await self.authenticate()
        window_start = date.today() - timedelta(days=SYNC_WINDOW_DAYS)
        restriction = ACTIVE_CUSTOMERS_RESTRICTION_TEMPLATE.format(
            window_start=(
                f"date({window_start.year},{window_start.month},{window_start.day})"
            )
        )
        shortname = quote(self.settings.maconomy_shortname, safe="")
        url = (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/customercard/filter"
        )
        try:
            response = await self.client.post(
                url,
                headers={
                    "Accept": CONTAINER_ACCEPT,
                    "Content-Type": CONTAINER_CONTENT_TYPE,
                    "Authorization": f"X-Reconnect {reconnect_token}",
                },
                json={
                    "restriction": restriction,
                    "fields": CUSTOMER_CARD_FIELDS,
                    "limit": 5000,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyError(
                "Maconomy customer card request failed",
                stage="customer_discovery",
                reason=(
                    "http_status"
                    if isinstance(exc, httpx.HTTPStatusError)
                    else "request_error"
                ),
                upstream_status=(
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                ),
            ) from exc

        try:
            records = response.json()["panes"]["filter"]["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyError(
                "Invalid Maconomy customer card response",
                stage="customer_discovery",
                reason="invalid_response",
                upstream_status=response.status_code,
            ) from exc
        if not isinstance(records, list):
            raise MaconomyError(
                "Invalid Maconomy customer card response",
                stage="customer_discovery",
                reason="invalid_records",
                upstream_status=response.status_code,
            )
        return [
            record["data"]
            for record in records
            if isinstance(record, dict)
            and isinstance(record.get("data"), dict)
        ]

    @staticmethod
    def classify_customers(
        customers: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Keep only new customers and customers newer than their checkpoint."""
        new_customers: list[dict[str, Any]] = []
        updated_customers: list[dict[str, Any]] = []

        for customer in customers:
            if not str(customer.get(CUSTOMER_NUMBER_FIELD) or "").strip():
                continue

            version = customer.get(VERSION_FIELD)
            version_text = str(version).strip() if version is not None else ""
            if not version_text:
                continue

            synced_version = customer.get(CUSTOMER_SYNCED_VERSION_FIELD)
            synced_text = (
                str(synced_version).strip() if synced_version is not None else ""
            )
            if not synced_text:
                new_customers.append({**customer, "action": "create"})
                continue

            try:
                if int(version_text) > int(synced_text):
                    updated_customers.append({**customer, "action": "update"})
            except ValueError:
                continue

        return {
            "new_customers": new_customers,
            "updated_customers": updated_customers,
        }
