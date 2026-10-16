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