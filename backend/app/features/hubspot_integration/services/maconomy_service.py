
import base64
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings


AUTH_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.authentication+json; "
    "charset=utf-8; version=3.0"
)

CONTAINER_ACCEPT = (
    "application/vnd.deltek.maconomy.containers+json; "
    "charset=utf-8; version=9.0"
)

CONTAINER_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.containers+json; "
    "charset=UTF-8; version=9.0"
)

CUSTOMER_CARD_FIELDS = [
    #"attention",
    "changeddate",
    "createddate",
    "country",
    "customerremark26",
    #customerimage",
    "customernumber",
    "departmentnumber",
    "electronicmailaddress",
    "entityname",
    #"instancekey",
    "locationname",
    "name1",
    "specification5name",
    "specification6name",
    "telephone",
    "versionnumber"
]


class CustomerCardServiceError(Exception):
    """Raised when Maconomy Customer Card retrieval fails."""


class CustomerCardService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self._reconnect_token: str | None = None

    async def authenticate(self) -> None:
        """Authenticate with Maconomy and retain the reconnect token."""
        if self._reconnect_token is not None:
            return

        credentials = (
            f"{self.settings.maconomy_username}:"
            f"{self.settings.maconomy_password.get_secret_value()}"
        )
        encoded = base64.b64encode(
            credentials.encode("utf-8")
        ).decode("ascii")

        shortname = quote(self.settings.maconomy_shortname, safe="")

        try:
            response = await self.client.get(
                f"{self.settings.maconomy_url}/maconomy-api/auth/"
                f"{shortname}/login",
                headers={
                    "Accept": AUTH_CONTENT_TYPE,
                    "Maconomy-Authentication": "X-Reconnect",
                    "Authorization": f"Basic {encoded}",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CustomerCardServiceError(
                "Maconomy authentication request failed"
            ) from exc

        token = response.headers.get("Maconomy-Reconnect", "").strip()

        if response.status_code != 204 or not token:
            raise CustomerCardServiceError(
                "Invalid Maconomy authentication response"
            )

        self._reconnect_token = token

    async def get_recent_customers(
        self,
    ) -> list[dict[str, Any]]:
        """Retrieve customers created or changed in the last two days."""
        await self.authenticate()

        shortname = quote(self.settings.maconomy_shortname, safe="")
        start_date = date.today() - timedelta(days=2)

        date_filter = (
            f"date({start_date.year},{start_date.month},{start_date.day})"
        )
        restriction = (
            f"(ActiveStatus = ActiveType'Active) and "
            f"(createddate>={date_filter} or changeddate>={date_filter})"
        )
        
        try:
            response = await self.client.post(
                f"{self.settings.maconomy_url}/maconomy-api/containers/"
                f"{shortname}/customercard/filter",
                headers={
                    "Accept": CONTAINER_ACCEPT,
                    "Content-Type": CONTAINER_CONTENT_TYPE,
                    "Authorization": f"X-Reconnect {self._reconnect_token}",
                },
                json={
                    "restriction": restriction,
                    "fields": CUSTOMER_CARD_FIELDS,
                    "limit": 5000,
                    "offset": 0,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CustomerCardServiceError(
                "Maconomy Customer Card request failed"
            ) from exc

        try:
            pane = response.json()["panes"]["filter"]
            metadata = pane["meta"]
            records = [item["data"] for item in pane["records"]]
            row_count = metadata["rowCount"]
            row_offset = metadata.get("rowOffset")
        except (KeyError, TypeError, ValueError) as exc:
            raise CustomerCardServiceError(
                "Invalid Maconomy Customer Card response"
            ) from exc

        if (
            isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or row_count != len(records)
            or (row_offset is not None and row_offset != 0)
            or not all(isinstance(record, dict) for record in records)
        ):
            raise CustomerCardServiceError(
                "Invalid Maconomy Customer Card response"
            )

        return records

    def classify_customers(
        self,
        customers: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Separate customers into create, update, and skip lists."""

        create_list: list[dict[str, Any]] = []
        update_list: list[dict[str, Any]] = []
        skip_list: list[dict[str, Any]] = []

        for customer in customers:
            current_version = customer.get("versionnumber")
            synced_version = customer.get("customerremark26")

            if synced_version is None or str(synced_version).strip() == "":
                create_list.append(customer)
                continue

            try:
                current_version = int(current_version)
                synced_version = int(synced_version)
            except (TypeError, ValueError):
                skip_list.append(customer)
                continue

            if current_version > synced_version:
                update_list.append(customer)
            elif current_version == synced_version:
                skip_list.append(customer)
            else:
                skip_list.append(customer)

        return {
            "create": create_list,
            "update": update_list,
            "skip": skip_list,
        }
