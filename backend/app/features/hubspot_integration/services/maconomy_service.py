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
CONTACT_CUSTOMER_FILTER_BATCH_SIZE = 50

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
    "name2",
    "name3",
    "postaldistrict",
    "specification5name",
    "specification6name",
    "telephone",
    "versionnumber",
    "zipcode",
]

CONTACT_PERSON_FIELDS = [
    "changeddate",
    "contactcompanynumber",
    "contactpersonnumber",
    "createddate",
    "country",
    "electronicmailaddress",
    "firstname",
    "lastname",
    "mobilephone",
    "name1",
    "name2",
    "position",
    "remark1",
    "remark5",
    "telephone",
    "telephone2",
    "personaltitle",
    "versionnumber",
]

CUSTOMER_NAME_LOOKUP_FIELDS = ["customernumber", "name1"]


class MaconomyServiceError(Exception):
    """Raised when Maconomy discovery or checkpoint write-back fails."""


class MaconomyRecordNotFoundError(MaconomyServiceError):
    """Raised when a requested Maconomy Customer or Contact does not exist."""


class MaconomyVersionConflictError(MaconomyServiceError):
    """Raised when a Maconomy record changes before checkpoint write-back."""


class MaconomyService:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self.timeout = 60.0
        self._reconnect_token: str | None = None

    def _require_client(self) -> httpx.AsyncClient:
        if self.client is None:
            raise MaconomyServiceError("Maconomy HTTP client is not configured")
        return self.client

    async def authenticate(self) -> str:
        """Authenticate once and reuse the reconnect token for this service run."""
        if self._reconnect_token:
            return self._reconnect_token

        client = self._require_client()
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
            response = await client.get(
                url,
                headers={
                    "Accept": AUTH_CONTENT_TYPE,
                    "Maconomy-Authentication": "X-Reconnect",
                    "Authorization": f"Basic {encoded_credentials}",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy authentication failed") from exc

        token = response.headers.get("Maconomy-Reconnect", "").strip()
        if response.status_code != 204 or not token:
            raise MaconomyServiceError("Maconomy authentication failed")

        self._reconnect_token = token
        return token

    @staticmethod
    def _container_headers(reconnect_token: str) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }

    def _container_url(self, container: str) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/{container}"
        )

    def _customer_card_url(self) -> str:
        return self._container_url("customercard")

    def _contact_persons_url(self) -> str:
        return self._container_url("contactpersons")

    @staticmethod
    def _recent_date_filter() -> str:
        start_date = date.today() - timedelta(days=SYNC_WINDOW_DAYS)
        return f"date({start_date.year},{start_date.month},{start_date.day})"

    @staticmethod
    def _get_sync_decision(
        record: dict[str, Any],
        synced_version_field: str,
    ) -> tuple[str | None, str | None]:
        synced_version = record.get(synced_version_field)
        if synced_version is None or str(synced_version).strip() == "":
            return "create", None

        try:
            current_version = int(record.get("versionnumber"))
            previous_version = int(synced_version)
        except (TypeError, ValueError):
            return None, "invalid version or sync version"

        if current_version > previous_version:
            return "update", None
        if current_version < previous_version:
            return None, "sync version is greater than source version"
        return None, None

    @staticmethod
    def _get_sync_action(
        record: dict[str, Any],
        synced_version_field: str,
    ) -> str | None:
        action, _ = MaconomyService._get_sync_decision(
            record,
            synced_version_field,
        )
        return action

    async def get_sync_candidates(self) -> dict[str, list[dict[str, Any]]]:
        """Return independently classified customer and contact work lists."""
        client = self._require_client()
        reconnect_token = await self.authenticate()

        try:
            customers = await self._get_recent_customers(
                client,
                reconnect_token,
            )
            recent_contacts = await self._get_recent_contact_persons(
                client,
                reconnect_token,
            )
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy request failed") from exc

        new_customers: list[dict[str, Any]] = []
        updated_customers: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for customer in customers:
            customer_number = str(
                customer.get("customernumber") or ""
            ).strip()
            if not customer_number:
                skipped.append(
                    {
                        "entity_type": "customer",
                        "source_id": None,
                        "reason": "missing or empty customernumber",
                    }
                )
                continue

            action, reason = self._get_sync_decision(
                customer,
                CUSTOMER_SYNCED_VERSION_FIELD,
            )
            if action == "create":
                new_customers.append(
                    {**customer, "action": "create", "contactperson": []}
                )
            elif action == "update":
                updated_customers.append({**customer, "action": "update"})
            elif reason:
                skipped.append(
                    {
                        "entity_type": "customer",
                        "source_id": customer_number,
                        "reason": reason,
                    }
                )

        new_customer_numbers = {
            str(customer["customernumber"]).strip()
            for customer in new_customers
        }
        complete_new_customer_contacts = (
            await self._get_contact_persons_for_customers(
                client,
                reconnect_token,
                sorted(new_customer_numbers),
            )
            if new_customer_numbers
            else []
        )

        contacts_for_new_customers: dict[str, dict[str, Any]] = {}
        for contact in [*complete_new_customer_contacts, *recent_contacts]:
            contact_number = str(
                contact.get("contactpersonnumber") or ""
            ).strip()
            parent_number = str(
                contact.get("contactcompanynumber") or ""
            ).strip()
            if contact_number and parent_number in new_customer_numbers:
                contacts_for_new_customers[contact_number] = {
                    **contact,
                    "action": "create",
                }

        contacts_by_parent: dict[str, list[dict[str, Any]]] = {}
        for contact in contacts_for_new_customers.values():
            parent_number = str(contact["contactcompanynumber"]).strip()
            contacts_by_parent.setdefault(parent_number, []).append(contact)

        for customer in new_customers:
            customer_number = str(customer["customernumber"]).strip()
            customer["contactperson"] = contacts_by_parent.get(
                customer_number,
                [],
            )

        new_contacts_for_existing_customers: list[dict[str, Any]] = []
        updated_contacts: list[dict[str, Any]] = []
        seen_contacts: set[str] = set()

        for contact in recent_contacts:
            contact_number = str(
                contact.get("contactpersonnumber") or ""
            ).strip()
            parent_number = str(
                contact.get("contactcompanynumber") or ""
            ).strip()

            if not contact_number:
                skipped.append(
                    {
                        "entity_type": "contact",
                        "source_id": None,
                        "reason": "missing or empty contactpersonnumber",
                    }
                )
                continue
            if contact_number in seen_contacts:
                continue
            seen_contacts.add(contact_number)
            if parent_number in new_customer_numbers:
                continue
            if not parent_number:
                skipped.append(
                    {
                        "entity_type": "contact",
                        "source_id": contact_number,
                        "reason": "missing or empty contactcompanynumber",
                    }
                )
                continue

            action, reason = self._get_sync_decision(
                contact,
                CONTACT_SYNCED_VERSION_FIELD,
            )
            if action == "create":
                new_contacts_for_existing_customers.append(
                    {
                        **contact,
                        "action": "create",
                        "parent_customer_status": "existing",
                    }
                )
            elif action == "update":
                updated_contacts.append({**contact, "action": "update"})
            elif reason:
                skipped.append(
                    {
                        "entity_type": "contact",
                        "source_id": contact_number,
                        "reason": reason,
                    }
                )

        return {
            "new_customers": new_customers,
            "updated_customers": updated_customers,
            "new_contacts_for_existing_customers": (
                new_contacts_for_existing_customers
            ),
            "updated_contacts": updated_contacts,
            "skipped": skipped,
        }

    async def get_customers_with_contact_persons(self) -> list[dict[str, Any]]:
        """Compatibility view of the classified customer lists."""
        if self.client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                service = MaconomyService(client, self.settings)
                return await service.get_customers_with_contact_persons()

        candidates = await self.get_sync_candidates()
        return [
            *candidates["new_customers"],
            *candidates["updated_customers"],
        ]

    async def get_customer_with_contact_persons(
        self,
        customer_number: str,
    ) -> dict[str, Any]:
        """Retrieve one active Customer and its complete Contact list."""
        client = self._require_client()
        reconnect_token = await self.authenticate()
        escaped_number = customer_number.replace("'", "''")

        try:
            customers = await self._filter_records(
                client,
                reconnect_token,
                self._customer_card_url(),
                (
                    "(ActiveStatus = ActiveType'Active) and "
                    f"(customernumber = '{escaped_number}')"
                ),
                CUSTOMER_CARD_FIELDS,
                "customer card",
            )
            contacts = await self._get_contact_persons_for_customers(
                client,
                reconnect_token,
                [customer_number],
            )
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy request failed") from exc

        matching = [
            customer
            for customer in customers
            if str(customer.get("customernumber") or "").strip()
            == customer_number
        ]
        if len(matching) != 1:
            raise MaconomyRecordNotFoundError(
                f"Maconomy Customer {customer_number} was not found"
            )

        return {
            **matching[0],
            "action": "manual_sync",
            "contactperson": [
                {**contact, "action": "manual_sync"}
                for contact in contacts
            ],
        }

    async def get_contact_person(
        self,
        contact_person_number: str,
    ) -> dict[str, Any]:
        """Retrieve one Contact Person for a manual synchronization retry."""
        client = self._require_client()
        reconnect_token = await self.authenticate()
        escaped_number = contact_person_number.replace("'", "''")

        try:
            contacts = await self._filter_records(
                client,
                reconnect_token,
                self._contact_persons_url(),
                f"contactpersonnumber = '{escaped_number}'",
                CONTACT_PERSON_FIELDS,
                "contact persons",
            )
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy request failed") from exc

        matching = [
            contact
            for contact in contacts
            if str(contact.get("contactpersonnumber") or "").strip()
            == contact_person_number
        ]
        if len(matching) != 1:
            raise MaconomyRecordNotFoundError(
                f"Maconomy Contact Person {contact_person_number} was not found"
            )
        return {**matching[0], "action": "manual_sync"}

    async def get_customer_names(
        self, customer_numbers: list[str]
    ) -> dict[str, str]:
        """Return {customernumber: name1} for the requested customers.

        Batched (50 per filter call, mirroring
        _get_contact_persons_for_customers); customers not found or with an
        empty name1 are simply absent from the result.
        """
        if not customer_numbers:
            return {}
        client = self._require_client()
        reconnect_token = await self.authenticate()
        names: dict[str, str] = {}
        try:
            for offset in range(
                0,
                len(customer_numbers),
                CONTACT_CUSTOMER_FILTER_BATCH_SIZE,
            ):
                batch = customer_numbers[
                    offset : offset + CONTACT_CUSTOMER_FILTER_BATCH_SIZE
                ]
                clauses = [
                    "customernumber = "
                    f"'{number.replace(chr(39), chr(39) * 2)}'"
                    for number in batch
                ]
                records = await self._filter_records(
                    client,
                    reconnect_token,
                    self._customer_card_url(),
                    " or ".join(f"({clause})" for clause in clauses),
                    CUSTOMER_NAME_LOOKUP_FIELDS,
                    "customer card",
                )
                for record in records:
                    customer_number = str(
                        record.get("customernumber") or ""
                    ).strip()
                    name1 = str(record.get("name1") or "").strip()
                    if customer_number and name1:
                        names[customer_number] = name1
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy request failed") from exc
        return names

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
        return await self._filter_records(
            client,
            reconnect_token,
            self._customer_card_url(),
            restriction,
            CUSTOMER_CARD_FIELDS,
            "customer card",
        )

    async def _get_recent_contact_persons(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> list[dict[str, Any]]:
        date_filter = self._recent_date_filter()
        restriction = f"createddate>={date_filter} or changeddate>={date_filter}"
        return await self._filter_records(
            client,
            reconnect_token,
            self._contact_persons_url(),
            restriction,
            CONTACT_PERSON_FIELDS,
            "contact persons",
        )

    async def _get_contact_persons_for_customers(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        customer_numbers: list[str],
    ) -> list[dict[str, Any]]:
        records_by_id: dict[str, dict[str, Any]] = {}
        for offset in range(
            0,
            len(customer_numbers),
            CONTACT_CUSTOMER_FILTER_BATCH_SIZE,
        ):
            batch = customer_numbers[
                offset : offset + CONTACT_CUSTOMER_FILTER_BATCH_SIZE
            ]
            clauses = [
                "contactcompanynumber = "
                f"'{number.replace(chr(39), chr(39) * 2)}'"
                for number in batch
            ]
            records = await self._filter_records(
                client,
                reconnect_token,
                self._contact_persons_url(),
                " or ".join(f"({clause})" for clause in clauses),
                CONTACT_PERSON_FIELDS,
                "contact persons",
            )
            for record in records:
                contact_number = str(
                    record.get("contactpersonnumber") or ""
                ).strip()
                if contact_number:
                    records_by_id[contact_number] = record
        return list(records_by_id.values())

    async def _filter_records(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        container_url: str,
        restriction: str,
        fields: list[str],
        response_name: str,
    ) -> list[dict[str, Any]]:
        response = await client.post(
            f"{container_url}/filter",
            headers=self._container_headers(reconnect_token),
            json={
                "restriction": restriction,
                "fields": fields,
                "limit": 5000,
            },
        )
        response.raise_for_status()

        try:
            records = response.json()["panes"]["filter"]["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                f"Invalid Maconomy {response_name} response"
            ) from exc

        return [
            record["data"]
            for record in records
            if isinstance(record, dict)
            and isinstance(record.get("data"), dict)
        ]

    async def update_customer_sync_version(
        self,
        customer_number: str,
        current_version_number: int | str,
    ) -> dict[str, Any]:
        return await self._update_sync_version(
            container="customercard",
            key_field="customernumber",
            key_value=customer_number,
            checkpoint_field=CUSTOMER_SYNCED_VERSION_FIELD,
            current_version_number=current_version_number,
        )

    async def update_contact_sync_version(
        self,
        contact_person_number: str,
        current_version_number: int | str,
    ) -> dict[str, Any]:
        return await self._update_sync_version(
            container="contactpersons",
            key_field="contactpersonnumber",
            key_value=contact_person_number,
            checkpoint_field=CONTACT_SYNCED_VERSION_FIELD,
            current_version_number=current_version_number,
        )

    async def _update_sync_version(
        self,
        *,
        container: str,
        key_field: str,
        key_value: str,
        checkpoint_field: str,
        current_version_number: int | str,
    ) -> dict[str, Any]:
        try:
            expected_version = int(current_version_number)
        except (TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                f"Invalid version number for {checkpoint_field} update"
            ) from exc

        try:
            return await self._attempt_sync_version_update(
                container=container,
                key_field=key_field,
                key_value=key_value,
                checkpoint_field=checkpoint_field,
                expected_version=expected_version,
            )
        except MaconomyVersionConflictError:
            return await self._attempt_sync_version_update(
                container=container,
                key_field=key_field,
                key_value=key_value,
                checkpoint_field=checkpoint_field,
                expected_version=None,
            )

    async def _attempt_sync_version_update(
        self,
        *,
        container: str,
        key_field: str,
        key_value: str,
        checkpoint_field: str,
        expected_version: int | None,
    ) -> dict[str, Any]:
        client = self._require_client()
        reconnect_token = await self.authenticate()
        container_url = self._container_url(container)
        headers = self._container_headers(reconnect_token)

        record, instance_id, bound_token = await self._bind_sync_record(
            container=container,
            key_field=key_field,
            key_value=key_value,
            checkpoint_field=checkpoint_field,
        )
        try:
            bound_version = int(record.get("versionnumber"))
        except (TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                f"Invalid Maconomy version for {container} record {key_value}"
            ) from exc

        if expected_version is not None and bound_version != expected_version:
            raise MaconomyVersionConflictError(
                f"Maconomy {container} record {key_value} changed "
                "before its sync version could be saved"
            )

        source_version = bound_version
        checkpoint_value = str(source_version + 1)
        try:
            update_response = await client.post(
                f"{container_url}/instances/{instance_id}/data/panes/card/0",
                headers={
                    **headers,
                    "Maconomy-Concurrency-Control": bound_token,
                },
                json={
                    "data": {checkpoint_field: checkpoint_value},
                    "offset": 0,
                    "limit": 100,
                },
            )
            update_response.raise_for_status()
        except httpx.HTTPError as exc:
            if (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code in (409, 412)
            ):
                raise MaconomyVersionConflictError(
                    f"Maconomy {container} record {key_value} changed "
                    "during sync-version write-back"
                ) from exc
            raise MaconomyServiceError(
                f"Maconomy {checkpoint_field} update failed"
            ) from exc

        saved_record, _, _ = await self._bind_sync_record(
            container=container,
            key_field=key_field,
            key_value=key_value,
            checkpoint_field=checkpoint_field,
        )
        try:
            saved_version = int(saved_record.get("versionnumber"))
        except (TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                f"Invalid saved Maconomy version for {container} record {key_value}"
            ) from exc

        if saved_version != source_version + 1:
            raise MaconomyServiceError(
                f"Maconomy {container} record {key_value} version did not "
                "increase by one"
            )
        if str(saved_record.get(checkpoint_field) or "").strip() != checkpoint_value:
            raise MaconomyServiceError(
                f"Maconomy {container} record {key_value} "
                f"{checkpoint_field} write could not be verified"
            )

        return {
            "source_id": str(key_value),
            "checkpoint_field": checkpoint_field,
            "checkpoint_value": checkpoint_value,
            "versionnumber": saved_version,
            "conflict_retried": expected_version is None,
        }

    async def _bind_sync_record(
        self,
        *,
        container: str,
        key_field: str,
        key_value: str,
        checkpoint_field: str,
    ) -> tuple[dict[str, Any], str, str]:
        client = self._require_client()
        reconnect_token = await self.authenticate()
        container_url = self._container_url(container)
        headers = self._container_headers(reconnect_token)

        try:
            instance_response = await client.post(
                f"{container_url}/instances",
                headers=headers,
                json={
                    "panes": {
                        "card": {
                            "fields": [
                                key_field,
                                checkpoint_field,
                                "versionnumber",
                            ]
                        }
                    }
                },
            )
            instance_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyServiceError(
                f"Maconomy {container} instance request failed"
            ) from exc

        try:
            instance_id = str(
                instance_response.json()["meta"]["containerInstanceId"]
            ).strip()
            concurrency_token = (
                instance_response.headers.get("Maconomy-Concurrency-Control")
                or ""
            ).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy instance response"
            ) from exc
        if not instance_id or not concurrency_token:
            raise MaconomyServiceError("Invalid Maconomy instance response")

        try:
            bind_response = await client.post(
                f"{container_url}/instances/{instance_id}/data;"
                f"{key_field}={quote(str(key_value), safe='')}",
                headers={
                    **headers,
                    "Maconomy-Concurrency-Control": concurrency_token,
                },
                json={},
            )
            bind_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyServiceError(
                f"Maconomy {container} bind request failed"
            ) from exc

        bound_token = (
            bind_response.headers.get("Maconomy-Concurrency-Control") or ""
        ).strip()
        if not bound_token:
            raise MaconomyServiceError("Invalid Maconomy bind response")

        try:
            records = [
                item["data"]
                for item in bind_response.json()["panes"]["card"]["records"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy bind response"
            ) from exc

        matching = [
            record
            for record in records
            if isinstance(record, dict)
            and str(record.get(key_field) or "").strip() == str(key_value).strip()
        ]
        if len(matching) != 1:
            raise MaconomyServiceError(
                f"Maconomy {container} record {key_value} was not found"
            )
        return matching[0], instance_id, bound_token
