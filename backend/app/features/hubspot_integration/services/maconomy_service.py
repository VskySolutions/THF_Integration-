
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

    def _contactcompanys_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/contactcompanys"
        )

    async def bind_contact_company_instance(
        self,
        customer_number: str,
    ) -> tuple[dict[str, Any], str, str]:
        """Initialize a contactcompanys instance and bind it to a company.

        Returns ``(record, instance_id, concurrency_token)``. The
        concurrency token is refreshed from the bind response and must be
        passed to :meth:`update_contact_company_version`.
        """
        await self.authenticate()

        headers = {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {self._reconnect_token}",
        }

        try:
            instance_response = await self.client.post(
                f"{self._contactcompanys_url()}/instances",
                headers=headers,
                json={
                    "panes": {
                        "card": {
                            "fields": [
                                "customernumber",
                                "remarks5",
                                "versionnumber",
                            ]
                        }
                    }
                },
            )
            instance_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CustomerCardServiceError(
                "Maconomy contact company instance request failed"
            ) from exc

        try:
            instance_id_value = instance_response.json()["meta"][
                "containerInstanceId"
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise CustomerCardServiceError(
                "Invalid Maconomy instance response"
            ) from exc

        if not instance_id_value or not str(instance_id_value).strip():
            raise CustomerCardServiceError(
                "Invalid Maconomy instance response"
            )
        instance_id = str(instance_id_value).strip()

        concurrency_token = (
            instance_response.headers.get("Maconomy-Concurrency-Control")
            or ""
        ).strip()
        if not concurrency_token:
            raise CustomerCardServiceError(
                "Invalid Maconomy instance response"
            )

        bind_headers = {
            **headers,
            "Maconomy-Concurrency-Control": concurrency_token,
        }
        try:
            bind_response = await self.client.post(
                f"{self._contactcompanys_url()}/instances/{instance_id}"
                f"/data;customernumber={quote(customer_number, safe='')}",
                headers=bind_headers,
                json={},
            )
            bind_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CustomerCardServiceError(
                "Maconomy contact company bind request failed"
            ) from exc

        bound_token = (
            bind_response.headers.get("Maconomy-Concurrency-Control") or ""
        ).strip()
        if not bound_token:
            raise CustomerCardServiceError(
                "Invalid Maconomy bind response"
            )

        try:
            pane = bind_response.json()["panes"]["card"]
            records = [item["data"] for item in pane["records"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise CustomerCardServiceError(
                "Invalid Maconomy bind response"
            ) from exc

        matching = [
            record
            for record in records
            if isinstance(record, dict)
            and str(record.get("customernumber") or "").strip()
            == str(customer_number).strip()
        ]
        if len(matching) != 1:
            raise CustomerCardServiceError(
                f"Maconomy contact company {customer_number} was not found"
            )

        return matching[0], instance_id, bound_token

    async def update_contact_company_version(
        self,
        *,
        instance_id: str,
        concurrency_token: str,
        current_version_number: int | str,
    ) -> dict[str, Any]:
        """Write ``remarks5 = versionnumber + 1`` to a bound company card.

        The caller supplies the input ``versionnumber``; this method
        increments it by one and posts it to the card pane.
        """
        await self.authenticate()

        try:
            new_remarks5 = str(int(current_version_number) + 1)
        except (TypeError, ValueError) as exc:
            raise CustomerCardServiceError(
                "Invalid version number for remarks5 update"
            ) from exc

        headers = {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {self._reconnect_token}",
            "Maconomy-Concurrency-Control": concurrency_token,
        }

        try:
            response = await self.client.post(
                f"{self._contactcompanys_url()}/instances/{instance_id}"
                "/data/panes/card/0",
                headers=headers,
                json={
                    "data": {"remarks5": new_remarks5},
                    "offset": 0,
                    "limit": 100,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CustomerCardServiceError(
                "Maconomy contact company remarks5 update failed"
            ) from exc

        return {"instance_id": instance_id, "remarks5": new_remarks5}

    def _contactpersons_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/contactpersons"
        )

    async def bind_contact_person_instance(
        self,
        contact_person_number: str,
    ) -> tuple[dict[str, Any], str, str]:
        """Initialize a contactpersons instance and bind it to a contact.

        Returns ``(record, instance_id, concurrency_token)``. The
        concurrency token is refreshed from the bind response and must be
        passed to :meth:`update_contact_person_version`.
        """
        await self.authenticate()

        headers = {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {self._reconnect_token}",
        }

        try:
            instance_response = await self.client.post(
                f"{self._contactpersons_url()}/instances",
                headers=headers,
                json={
                    "panes": {
                        "card": {
                            "fields": [
                                "contactpersonnumber",
                                "remarks5",
                                "versionnumber",
                            ]
                        }
                    }
                },
            )
            instance_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CustomerCardServiceError(
                "Maconomy contact person instance request failed"
            ) from exc

        try:
            instance_id_value = instance_response.json()["meta"][
                "containerInstanceId"
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise CustomerCardServiceError(
                "Invalid Maconomy instance response"
            ) from exc

        if not instance_id_value or not str(instance_id_value).strip():
            raise CustomerCardServiceError(
                "Invalid Maconomy instance response"
            )
        instance_id = str(instance_id_value).strip()

        concurrency_token = (
            instance_response.headers.get("Maconomy-Concurrency-Control")
            or ""
        ).strip()
        if not concurrency_token:
            raise CustomerCardServiceError(
                "Invalid Maconomy instance response"
            )

        bind_headers = {
            **headers,
            "Maconomy-Concurrency-Control": concurrency_token,
        }
        try:
            bind_response = await self.client.post(
                f"{self._contactpersons_url()}/instances/{instance_id}"
                f"/data;contactpersonnumber="
                f"{quote(contact_person_number, safe='')}",
                headers=bind_headers,
                json={},
            )
            bind_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CustomerCardServiceError(
                "Maconomy contact person bind request failed"
            ) from exc

        bound_token = (
            bind_response.headers.get("Maconomy-Concurrency-Control") or ""
        ).strip()
        if not bound_token:
            raise CustomerCardServiceError(
                "Invalid Maconomy bind response"
            )

        try:
            pane = bind_response.json()["panes"]["card"]
            records = [item["data"] for item in pane["records"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise CustomerCardServiceError(
                "Invalid Maconomy bind response"
            ) from exc

        matching = [
            record
            for record in records
            if isinstance(record, dict)
            and str(record.get("contactpersonnumber") or "").strip()
            == str(contact_person_number).strip()
        ]
        if len(matching) != 1:
            raise CustomerCardServiceError(
                f"Maconomy contact person {contact_person_number} "
                "was not found"
            )

        return matching[0], instance_id, bound_token

    async def update_contact_person_version(
        self,
        *,
        instance_id: str,
        concurrency_token: str,
        current_version_number: int | str,
    ) -> dict[str, Any]:
        """Write ``remarks5 = versionnumber + 1`` to a bound contact card.

        The caller supplies the input ``versionnumber``; this method
        increments it by one and posts it to the card pane.
        """
        await self.authenticate()

        try:
            new_remarks5 = str(int(current_version_number) + 1)
        except (TypeError, ValueError) as exc:
            raise CustomerCardServiceError(
                "Invalid version number for remarks5 update"
            ) from exc

        headers = {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {self._reconnect_token}",
            "Maconomy-Concurrency-Control": concurrency_token,
        }

        try:
            response = await self.client.post(
                f"{self._contactpersons_url()}/instances/{instance_id}"
                "/data/panes/card/0",
                headers=headers,
                json={
                    "data": {"remarks5": new_remarks5},
                    "offset": 0,
                    "limit": 100,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CustomerCardServiceError(
                "Maconomy contact person remarks5 update failed"
            ) from exc

        return {"instance_id": instance_id, "remarks5": new_remarks5}
