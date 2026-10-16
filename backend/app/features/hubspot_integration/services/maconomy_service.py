import base64
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings

AUTH_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.authentication+json; charset=utf-8; version=3.0"
)
CONTAINER_ACCEPT = (
    "application/vnd.deltek.maconomy.containers+json; charset=utf-8; version=9.0"
)
CONTAINER_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.containers+json; charset=UTF-8; version=9.0"
)

SYNC_WINDOW_DAYS = 2
CUSTOMER_SYNCED_VERSION_FIELD = "customerremark26"
CONTACT_SYNCED_VERSION_FIELD = "remark5"

CUSTOMER_CARD_FIELDS = [
    "changeddate",
    "createddate",
    "country",
    "customerremark26",
    "customernumber",
    "departmentnumber",
    "electronicmailaddress",
    "entityname",
    "locationname",
    "name1",
    "specification5name",
    "specification6name",
    "telephone",
    "versionnumber",
]

CONTACT_PERSON_FIELDS = [
    "changeddate",
    "contactcompanynumber",
    "contactpersonnumber",
    "createddate",
    "electronicmailaddress",
    "firstname",
    "lastname",
    "name1",
    "position",
    "remark1",
    "remark5",
    "telephone",
    "telephone2",
    "versionnumber",
]


class MaconomyServiceError(Exception):
    pass


class MaconomyService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    async def _get_reconnect_token(self, client: httpx.AsyncClient) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        url = f"{self.settings.maconomy_url}/maconomy-api/auth/{shortname}/login"
        credentials = (
            f"{self.settings.maconomy_username}:"
            f"{self.settings.maconomy_password.get_secret_value()}"
        )
        encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode(
            "ascii"
        )

        response = await client.get(
            url,
            headers={
                "Accept": AUTH_CONTENT_TYPE,
                "Maconomy-Authentication": "X-Reconnect",
                "Authorization": f"Basic {encoded_credentials}",
            },
        )
        response.raise_for_status()

        token = response.headers.get("Maconomy-Reconnect", "").strip()

        if response.status_code != 204 or not token:
            raise MaconomyServiceError("Maconomy authentication failed")
        return token

    @staticmethod
    def _container_headers(reconnect_token: str) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }

    def _customer_card_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return f"{self.settings.maconomy_url}/maconomy-api/containers/{shortname}/customercard"

    def _contact_persons_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return f"{self.settings.maconomy_url}/maconomy-api/containers/{shortname}/contactpersons"

    @staticmethod
    def _recent_date_filter() -> str:
        start_date = date.today() - timedelta(days=SYNC_WINDOW_DAYS)
        return f"date({start_date.year},{start_date.month},{start_date.day})"

    @staticmethod
    def _get_sync_action(
        record: dict[str, Any],
        synced_version_field: str,
    ) -> str | None:
        synced_version = record.get(synced_version_field)

        if synced_version is None or str(synced_version).strip() == "":
            return "create"

        try:
            current_version = int(record.get("versionnumber"))
            synced_version = int(synced_version)
        except (TypeError, ValueError):
            return None

        if current_version > synced_version:
            return "update"
        return None


# ==================== Get customers with contact persons from Maconomy ====================
    async def get_customers_with_contact_persons(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)
                customers = await self._get_recent_customers(
                    client, reconnect_token
                )
                contact_persons = await self._get_recent_contact_persons(
                    client, reconnect_token
                )
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy request failed") from exc

        return self._build_customers_with_contact_persons(
            customers, contact_persons
        )

    def _build_customers_with_contact_persons(
        self,
        customers: list[dict[str, Any]],
        contact_persons: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        contacts_by_company: dict[str, list[dict[str, Any]]] = {}
        for contact in contact_persons:
            action = self._get_sync_action(contact, CONTACT_SYNCED_VERSION_FIELD)
            if action is None:
                continue
            company_number = str(contact.get("contactcompanynumber") or "").strip()
            contacts_by_company.setdefault(company_number, []).append(
                {**contact, "action": action}
            )

        result: list[dict[str, Any]] = []
        for customer in customers:
            action = self._get_sync_action(customer, CUSTOMER_SYNCED_VERSION_FIELD)
            if action is None:
                continue
            customer_number = str(customer.get("customernumber") or "").strip()
            result.append(
                {
                    **customer,
                    "action": action,
                    "contactperson": contacts_by_company.pop(customer_number, []),
                }
            )

        unmatched_contacts = [
            contact.get("contactpersonnumber")
            for contacts in contacts_by_company.values()
            for contact in contacts
        ]
        if unmatched_contacts:
            print(
                "Contact persons not included (customer not in this sync):",
                unmatched_contacts,
            )

        return result

    async def _get_recent_customers(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> list[dict[str, Any]]:
        date_filter = self._recent_date_filter()
        restriction = (
            f"(ActiveStatus = ActiveType'Active) and "
            f"(createddate>={date_filter} or changeddate>={date_filter})"
        )
        payload = {
            "restriction": restriction,
            "fields": CUSTOMER_CARD_FIELDS,
            "limit": 5000,
        }

        response = await client.post(
            f"{self._customer_card_url()}/filter",
            headers=self._container_headers(reconnect_token),
            json=payload,
        )
        response.raise_for_status()

        try:
            records = response.json()["panes"]["filter"]["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy customer card response") from exc

        return [
            record["data"]
            for record in records
            if isinstance(record, dict) and isinstance(record.get("data"), dict)
        ]

    # async def _get_recent_contact_persons(
    #     self,
    #     customers: list[dict[str, Any]],
    # ) -> dict[str, list[dict[str, Any]]]:
    #     """Separate customers into create, update, and skip lists."""

    #     create_list: list[dict[str, Any]] = []
    #     update_list: list[dict[str, Any]] = []
    #     skip_list: list[dict[str, Any]] = []

    #     for customer in customers:
    #         current_version = customer.get("versionnumber")
    #         synced_version = customer.get("customerremark26")

    #         if synced_version is None or str(synced_version).strip() == "":
    #             create_list.append(customer)
    #             continue

    #         try:
    #             current_version = int(current_version)
    #             synced_version = int(synced_version)
    #         except (TypeError, ValueError):
    #             skip_list.append(customer)
    #             continue

    #         if current_version > synced_version:
    #             update_list.append(customer)
    #         elif current_version == synced_version:
    #             skip_list.append(customer)
    #         else:
    #             skip_list.append(customer)

    #     return {
    #         "create": create_list,
    #         "update": update_list,
    #         "skip": skip_list,
    #     }



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
            raise MaconomyServiceError(
                "Maconomy contact company instance request failed"
            ) from exc

        try:
            instance_id_value = instance_response.json()["meta"][
                "containerInstanceId"
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy instance response"
            ) from exc

        if not instance_id_value or not str(instance_id_value).strip():
            raise MaconomyServiceError(
                "Invalid Maconomy instance response"
            )
        instance_id = str(instance_id_value).strip()

        concurrency_token = (
            instance_response.headers.get("Maconomy-Concurrency-Control")
            or ""
        ).strip()
        if not concurrency_token:
            raise MaconomyServiceError(
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
            raise MaconomyServiceError(
                "Maconomy contact company bind request failed"
            ) from exc

        bound_token = (
            bind_response.headers.get("Maconomy-Concurrency-Control") or ""
        ).strip()
        if not bound_token:
            raise MaconomyServiceError(
                "Invalid Maconomy bind response"
            )

        try:
            pane = bind_response.json()["panes"]["card"]
            records = [item["data"] for item in pane["records"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
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
            raise MaconomyServiceError(
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
            raise MaconomyServiceError(
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
            raise MaconomyServiceError(
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
            raise MaconomyServiceError(
                "Maconomy contact person instance request failed"
            ) from exc

        try:
            instance_id_value = instance_response.json()["meta"][
                "containerInstanceId"
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy instance response"
            ) from exc

        if not instance_id_value or not str(instance_id_value).strip():
            raise MaconomyServiceError(
                "Invalid Maconomy instance response"
            )
        instance_id = str(instance_id_value).strip()

        concurrency_token = (
            instance_response.headers.get("Maconomy-Concurrency-Control")
            or ""
        ).strip()
        if not concurrency_token:
            raise MaconomyServiceError(
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
            raise MaconomyServiceError(
                "Maconomy contact person bind request failed"
            ) from exc

        bound_token = (
            bind_response.headers.get("Maconomy-Concurrency-Control") or ""
        ).strip()
        if not bound_token:
            raise MaconomyServiceError(
                "Invalid Maconomy bind response"
            )

        try:
            pane = bind_response.json()["panes"]["card"]
            records = [item["data"] for item in pane["records"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
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
            raise MaconomyServiceError(
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
            raise MaconomyServiceError(
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
            raise MaconomyServiceError(
                "Maconomy contact person remarks5 update failed"
            ) from exc

        return {"instance_id": instance_id, "remarks5": new_remarks5}

    async def _get_recent_contact_persons(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> list[dict[str, Any]]:
        date_filter = self._recent_date_filter()
        restriction = f"createddate>={date_filter} or changeddate>={date_filter}"
        payload = {
            "restriction": restriction,
            "fields": CONTACT_PERSON_FIELDS,
            "limit": 5000,
        }
 
        response = await client.post(
            f"{self._contact_persons_url()}/filter",
            headers=self._container_headers(reconnect_token),
            json=payload,
        )
        response.raise_for_status()
 
        try:
            records = response.json()["panes"]["filter"]["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy contact persons response") from exc
 
        return [
            record["data"]
            for record in records
            if isinstance(record, dict) and isinstance(record.get("data"), dict)
        ]

    