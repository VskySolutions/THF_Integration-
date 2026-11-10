import asyncio
import base64
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.features.hubspot_contact_consolidated_integration.constants import (
    CONTACT_MASTER_FIELD,
    CONTACT_PERSON_FIELDS,
    CONTACT_SYNCED_VERSION_FIELD,
    CONTACT_COMPANY_NUMBER_FIELD,
    CONTACT_PERSON_NUMBER_FIELD,
    CUSTOMER_CARD_FIELDS,
    CUSTOMER_FILTER_BATCH_SIZE,
    CUSTOMER_NAME_LOOKUP_FIELDS,
    CUSTOMER_NUMBER_FIELD,
    CUSTOMER_SYNCED_VERSION_FIELD,
    EMAIL_BACK_QUERY_BATCH_SIZE,
    EMAIL_FIELD,
    MID_RUN_BACK_QUERY_CONCURRENCY,
    SYNC_WINDOW_DAYS,
    VERSION_FIELD,
)
from app.features.hubspot_contact_consolidated_integration.exceptions import (
    MaconomyError,
    MaconomyRecordNotFoundError,
    MaconomyVersionConflictError,
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
ACTIVE_CONTACTS_RESTRICTION_TEMPLATE = (
    "(contactcompanynumber!='null' and electronicmailaddress!='null') and "
    "(createddate>={window_start} or changeddate>={window_start})"
)


def _now_window_start() -> str:
    window_start = date.today() - timedelta(days=SYNC_WINDOW_DAYS)
    return f"date({window_start.year},{window_start.month},{window_start.day})"


class MaconomyService:
    """Maconomy container service; authenticates once and reuses the token."""

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
            raise MaconomyError("Maconomy HTTP client is not configured")
        return self.client

    async def authenticate(self) -> str:
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
            raise MaconomyError("Maconomy authentication failed") from exc

        token = response.headers.get("Maconomy-Reconnect", "").strip()
        if response.status_code != 204 or not token:
            raise MaconomyError("Maconomy authentication failed")

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

    async def discover_customers(self) -> list[dict[str, Any]]:
        """Active customers created/changed inside the sync window."""
        client = self._require_client()
        reconnect_token = await self.authenticate()
        restriction = ACTIVE_CUSTOMERS_RESTRICTION_TEMPLATE.format(
            window_start=_now_window_start()
        )
        return await self._filter_records(
            client,
            reconnect_token,
            self._customer_card_url(),
            restriction,
            CUSTOMER_CARD_FIELDS,
            "customer card",
        )

    async def discover_contact_persons(self) -> list[dict[str, Any]]:
        """Contact persons with a company and email, changed inside the window."""
        client = self._require_client()
        reconnect_token = await self.authenticate()
        restriction = ACTIVE_CONTACTS_RESTRICTION_TEMPLATE.format(
            window_start=_now_window_start()
        )
        return await self._filter_records(
            client,
            reconnect_token,
            self._contact_persons_url(),
            restriction,
            CONTACT_PERSON_FIELDS,
            "contact persons",
        )

    async def get_contacts_for_customers(
        self,
        customer_numbers: list[str],
    ) -> list[dict[str, Any]]:
        """Complete Contact Person list for the given customer numbers."""
        if not customer_numbers:
            return []
        client = self._require_client()
        reconnect_token = await self.authenticate()
        records_by_number: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(customer_numbers), CUSTOMER_FILTER_BATCH_SIZE):
            batch = customer_numbers[offset : offset + CUSTOMER_FILTER_BATCH_SIZE]
            clauses = [
                f"{CONTACT_COMPANY_NUMBER_FIELD} = "
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
                    record.get(CONTACT_PERSON_NUMBER_FIELD) or ""
                ).strip()
                if contact_number:
                    records_by_number[contact_number] = record
        return list(records_by_number.values())

    async def get_contact_persons_by_emails(
        self,
        emails: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Back-query ALL contact persons for the given emails, in batches.

        Batches of EMAIL_BACK_QUERY_BATCH_SIZE emails run with bounded
        parallelism; the union is grouped back by normalized email. Returns
        complete contact person records regardless of the sync window."""
        client = self._require_client()
        reconnect_token = await self.authenticate()
        unique_emails = list(dict.fromkeys(emails))

        async def run_batch(batch: list[str]) -> list[dict[str, Any]]:
            clauses = [
                f"{EMAIL_FIELD} like "
                f"'{email.replace(chr(39), chr(39) * 2)}'"
                for email in batch
            ]
            return await self._filter_records(
                client,
                reconnect_token,
                self._contact_persons_url(),
                " or ".join(f"({clause})" for clause in clauses),
                CONTACT_PERSON_FIELDS,
                "contact persons",
            )

        batches = [
            unique_emails[offset : offset + EMAIL_BACK_QUERY_BATCH_SIZE]
            for offset in range(0, len(unique_emails), EMAIL_BACK_QUERY_BATCH_SIZE)
        ]
        semaphore = asyncio.Semaphore(MID_RUN_BACK_QUERY_CONCURRENCY)

        async def run_limited(batch: list[str]) -> list[dict[str, Any]]:
            async with semaphore:
                return await run_batch(batch)

        results = await asyncio.gather(
            *(run_limited(batch) for batch in batches)
        )

        by_email: dict[str, list[dict[str, Any]]] = {}
        seen: set[str] = set()
        for records in results:
            for record in records:
                contact_number = str(
                    record.get(CONTACT_PERSON_NUMBER_FIELD) or ""
                ).strip()
                if not contact_number or contact_number in seen:
                    continue
                seen.add(contact_number)
                email = str(record.get(EMAIL_FIELD) or "").strip().lower()
                if email in unique_emails:
                    by_email.setdefault(email, []).append(record)
        return by_email

    async def get_customer_names(
        self,
        customer_numbers: list[str],
    ) -> dict[str, str]:
        if not customer_numbers:
            return {}
        client = self._require_client()
        reconnect_token = await self.authenticate()
        names: dict[str, str] = {}
        for offset in range(0, len(customer_numbers), CUSTOMER_FILTER_BATCH_SIZE):
            batch = customer_numbers[offset : offset + CUSTOMER_FILTER_BATCH_SIZE]
            clauses = [
                f"{CUSTOMER_NUMBER_FIELD} = "
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
                    record.get(CUSTOMER_NUMBER_FIELD) or ""
                ).strip()
                name1 = str(record.get("name1") or "").strip()
                if customer_number and name1:
                    names[customer_number] = name1
        return names

    async def get_customers_by_numbers(
        self,
        customer_numbers: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Customer card records fetched by number, regardless of the window.

        Used by the association phase (STEP H, historical parent recovery)
        to build Company payloads for parents that were never inside a sync
        window and were therefore not part of discovery."""
        unique_numbers = list(
            dict.fromkeys(
                str(number).strip()
                for number in customer_numbers
                if str(number).strip()
            )
        )
        if not unique_numbers:
            return {}
        client = self._require_client()
        reconnect_token = await self.authenticate()
        records_by_number: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(unique_numbers), CUSTOMER_FILTER_BATCH_SIZE):
            batch = unique_numbers[offset : offset + CUSTOMER_FILTER_BATCH_SIZE]
            clauses = [
                f"{CUSTOMER_NUMBER_FIELD} = "
                f"'{number.replace(chr(39), chr(39) * 2)}'"
                for number in batch
            ]
            records = await self._filter_records(
                client,
                reconnect_token,
                self._customer_card_url(),
                " or ".join(f"({clause})" for clause in clauses),
                CUSTOMER_CARD_FIELDS,
                "customer card",
            )
            for record in records:
                customer_number = str(
                    record.get(CUSTOMER_NUMBER_FIELD) or ""
                ).strip()
                if customer_number:
                    records_by_number[customer_number] = record
        return records_by_number

    async def get_customer_with_contacts(
        self,
        customer_number: str,
    ) -> dict[str, Any]:
        """One active Customer and its complete Contact Person list."""
        client = self._require_client()
        reconnect_token = await self.authenticate()
        escaped_number = customer_number.replace("'", "''")
        customers = await self._filter_records(
            client,
            reconnect_token,
            self._customer_card_url(),
            (
                "(ActiveStatus = ActiveType'Active) and "
                f"({CUSTOMER_NUMBER_FIELD} = '{escaped_number}')"
            ),
            CUSTOMER_CARD_FIELDS,
            "customer card",
        )
        matching = [
            customer
            for customer in customers
            if str(customer.get(CUSTOMER_NUMBER_FIELD) or "").strip()
            == customer_number
        ]
        if len(matching) != 1:
            raise MaconomyRecordNotFoundError(
                f"Maconomy Customer {customer_number} was not found"
            )
        contacts = await self.get_contacts_for_customers([customer_number])
        return {
            **matching[0],
            "contactperson": contacts,
        }

    async def get_contact_person(
        self,
        contact_person_number: str,
    ) -> dict[str, Any]:
        """One Contact Person record, regardless of the sync window."""
        client = self._require_client()
        reconnect_token = await self.authenticate()
        escaped_number = contact_person_number.replace("'", "''")
        contacts = await self._filter_records(
            client,
            reconnect_token,
            self._contact_persons_url(),
            f"{CONTACT_PERSON_NUMBER_FIELD} = '{escaped_number}'",
            CONTACT_PERSON_FIELDS,
            "contact persons",
        )
        matching = [
            contact
            for contact in contacts
            if str(contact.get(CONTACT_PERSON_NUMBER_FIELD) or "").strip()
            == contact_person_number
        ]
        if len(matching) != 1:
            raise MaconomyRecordNotFoundError(
                f"Maconomy Contact Person {contact_person_number} was not found"
            )
        return matching[0]

    @staticmethod
    def _classify_record(
        record: dict[str, Any],
        synced_version_field: str,
    ) -> tuple[str | None, str | None, str | None]:
        """Return (action, skip_reason, version_number) for one record."""
        synced_version = record.get(synced_version_field)
        if synced_version is None or str(synced_version).strip() == "":
            version = record.get("versionnumber")
            version_text = str(version).strip()
            if version_text:
                return "create", None, version_text
            return None, "invalid version number", None

        current_version = record.get(VERSION_FIELD)
        current_text = str(current_version).strip()
        if not current_text:
            return None, "invalid version number", None
        try:
            current = int(current_text)
            previous = int(synced_version)
        except (TypeError, ValueError):
            return None, "invalid version or sync version", current_text

        if current > previous:
            return "update", None, current_text
        if current < previous:
            return None, "sync version is greater than source version", current_text
        return None, None, current_text

    def classify_customers(
        self,
        customers: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        new_customers: list[dict[str, Any]] = []
        updated_customers: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for customer in customers:
            customer_number = str(customer.get(CUSTOMER_NUMBER_FIELD) or "").strip()
            if not customer_number:
                skipped.append(
                    {
                        "entity_type": "customer",
                        "source_id": None,
                        "reason": "missing or empty customernumber",
                    }
                )
                continue
            action, reason, _ = self._classify_record(
                customer, CUSTOMER_SYNCED_VERSION_FIELD
            )
            if action == "create":
                new_customers.append({**customer, "action": "create"})
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
        return {
            "new_customers": new_customers,
            "updated_customers": updated_customers,
            "skipped": skipped,
        }

    def classify_contact_persons(
        self,
        contacts: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        changed_contacts: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for contact in contacts:
            contact_number = str(
                contact.get(CONTACT_PERSON_NUMBER_FIELD) or ""
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
            if contact_number in seen:
                continue
            seen.add(contact_number)
            action, reason, _ = self._classify_record(
                contact, CONTACT_SYNCED_VERSION_FIELD
            )
            if action in ("create", "update"):
                changed_contacts.append({**contact, "action": action})
            elif reason:
                skipped.append(
                    {
                        "entity_type": "contact",
                        "source_id": contact_number,
                        "reason": reason,
                    }
                )
        return {
            "changed_contacts": changed_contacts,
            "skipped": skipped,
        }

    async def write_contact_master_stamp(
        self,
        contact_person_number: str,
        master_number: str,
    ) -> dict[str, Any]:
        """Write remark4 = master contact person number for one group member."""
        return await self._write_contact_field(
            contact_person_number=contact_person_number,
            field=CONTACT_MASTER_FIELD,
            value=str(master_number).strip(),
        )

    async def write_contact_sync_checkpoint(
        self,
        contact_person_number: str,
    ) -> dict[str, Any]:
        """Write remark5 = bound versionnumber + 1 for the master contact."""
        return await self._write_contact_field(
            contact_person_number=contact_person_number,
            field=CONTACT_SYNCED_VERSION_FIELD,
            value=None,
        )

    async def update_customer_sync_version(
        self,
        customer_number: str,
    ) -> dict[str, Any]:
        """Write customerremark26 = bound versionnumber + 1."""
        return await self._write_customer_field(
            customer_number=customer_number,
            field=CUSTOMER_SYNCED_VERSION_FIELD,
            value=None,
        )

    async def _write_contact_field(
        self,
        contact_person_number: str,
        field: str,
        value: str | None,
    ) -> dict[str, Any]:
        return await self._write_field(
            container="contactpersons",
            key_field=CONTACT_PERSON_NUMBER_FIELD,
            key_value=contact_person_number,
            checkpoint_field=field,
            checkpoint_value=value,
        )

    async def _write_customer_field(
        self,
        customer_number: str,
        field: str,
        value: str | None,
    ) -> dict[str, Any]:
        return await self._write_field(
            container="customercard",
            key_field=CUSTOMER_NUMBER_FIELD,
            key_value=customer_number,
            checkpoint_field=field,
            checkpoint_value=value,
        )

    async def _write_field(
        self,
        *,
        container: str,
        key_field: str,
        key_value: str,
        checkpoint_field: str,
        checkpoint_value: str | None,
    ) -> dict[str, Any]:
        try:
            return await self._attempt_field_write(
                container=container,
                key_field=key_field,
                key_value=key_value,
                checkpoint_field=checkpoint_field,
                checkpoint_value=checkpoint_value,
                strict=True,
            )
        except MaconomyVersionConflictError:
            return await self._attempt_field_write(
                container=container,
                key_field=key_field,
                key_value=key_value,
                checkpoint_field=checkpoint_field,
                checkpoint_value=checkpoint_value,
                strict=False,
            )

    async def _attempt_field_write(
        self,
        *,
        container: str,
        key_field: str,
        key_value: str,
        checkpoint_field: str,
        checkpoint_value: str | None,
        strict: bool,
    ) -> dict[str, Any]:
        client = self._require_client()
        reconnect_token = await self.authenticate()
        container_url = self._container_url(container)
        headers = self._container_headers(reconnect_token)

        record, instance_id, bound_token = await self._bind_record(
            client=client,
            container_url=container_url,
            headers=headers,
            container=container,
            key_field=key_field,
            key_value=key_value,
            checkpoint_field=checkpoint_field,
        )
        try:
            bound_version = int(record.get(VERSION_FIELD))
        except (TypeError, ValueError) as exc:
            raise MaconomyError(
                f"Invalid Maconomy version for {container} record {key_value}"
            ) from exc

        if checkpoint_value is None:
            checkpoint_value = str(bound_version + 1)

        source_version = bound_version
        update_response = None
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
                    "during its write-back"
                ) from exc
            raise MaconomyError(
                f"Maconomy {checkpoint_field} update failed for {key_value}"
            ) from exc

        saved_record, _, _ = await self._bind_record(
            client=client,
            container_url=container_url,
            headers=headers,
            container=container,
            key_field=key_field,
            key_value=key_value,
            checkpoint_field=checkpoint_field,
        )
        try:
            saved_version = int(saved_record.get(VERSION_FIELD))
        except (TypeError, ValueError) as exc:
            raise MaconomyError(
                f"Invalid saved Maconomy version for {container} record {key_value}"
            ) from exc

        if saved_version != source_version + 1:
            raise MaconomyError(
                f"Maconomy {container} record {key_value} version did not "
                "increase by one"
            )
        if str(saved_record.get(checkpoint_field) or "").strip() != checkpoint_value:
            raise MaconomyError(
                f"Maconomy {container} record {key_value} "
                f"{checkpoint_field} write could not be verified"
            )

        return {
            "source_id": str(key_value),
            "checkpoint_field": checkpoint_field,
            "checkpoint_value": checkpoint_value,
            "versionnumber": saved_version,
            "conflict_retried": not strict,
        }

    @staticmethod
    async def _bind_record(
        *,
        client: httpx.AsyncClient,
        container_url: str,
        headers: dict[str, str],
        container: str,
        key_field: str,
        key_value: str,
        checkpoint_field: str,
    ) -> tuple[dict[str, Any], str, str]:
        instance_response = await client.post(
            f"{container_url}/instances",
            headers=headers,
            json={
                "panes": {
                    "card": {
                        "fields": [
                            key_field,
                            checkpoint_field,
                            VERSION_FIELD,
                        ]
                    }
                }
            },
        )
        try:
            instance_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyError(
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
            raise MaconomyError("Invalid Maconomy instance response") from exc
        if not instance_id or not concurrency_token:
            raise MaconomyError("Invalid Maconomy instance response")

        bind_response = await client.post(
            f"{container_url}/instances/{instance_id}/data;"
            f"{key_field}={quote(str(key_value), safe='')}",
            headers={
                **headers,
                "Maconomy-Concurrency-Control": concurrency_token,
            },
            json={},
        )
        try:
            bind_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyError(
                f"Maconomy {container} bind request failed"
            ) from exc

        bound_token = (
            bind_response.headers.get("Maconomy-Concurrency-Control") or ""
        ).strip()
        if not bound_token:
            raise MaconomyError("Invalid Maconomy bind response")

        try:
            records = [
                item["data"]
                for item in bind_response.json()["panes"]["card"]["records"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyError("Invalid Maconomy bind response") from exc

        matching = [
            record
            for record in records
            if isinstance(record, dict)
            and str(record.get(key_field) or "").strip()
            == str(key_value).strip()
        ]
        if len(matching) != 1:
            raise MaconomyRecordNotFoundError(
                f"Maconomy {container} record {key_value} was not found"
            )
        return matching[0], instance_id, bound_token

    @staticmethod
    async def _filter_records(
        client: httpx.AsyncClient,
        reconnect_token: str,
        container_url: str,
        restriction: str,
        fields: list[str],
        response_name: str,
    ) -> list[dict[str, Any]]:
        response = await client.post(
            f"{container_url}/filter",
            headers=MaconomyService._container_headers(reconnect_token),
            json={
                "restriction": restriction,
                "fields": fields,
                "limit": 5000,
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyError(
                f"Maconomy {response_name} request failed"
            ) from exc

        try:
            records = response.json()["panes"]["filter"]["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyError(
                f"Invalid Maconomy {response_name} response"
            ) from exc

        return [
            record["data"]
            for record in records
            if isinstance(record, dict)
            and isinstance(record.get("data"), dict)
        ]
