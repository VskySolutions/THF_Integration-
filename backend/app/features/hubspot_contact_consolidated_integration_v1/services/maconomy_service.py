"""Read and write Maconomy customer and Contact Person records."""

import asyncio
import base64
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.features.hubspot_contact_consolidated_integration_v1.constants import (
    CONTACT_MASTER_FIELD,
    CONTACT_PERSON_FIELDS,
    CONTACT_PERSON_NUMBER_FIELD,
    CONTACT_SYNCED_VERSION_FIELD,
    CUSTOMER_CARD_FIELDS,
    CUSTOMER_NUMBER_FIELD,
    CUSTOMER_SYNCED_VERSION_FIELD,
    SPECIFICATION1_FIELDS,
    SPECIFICATION6_FIELDS,
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
ACTIVE_CONTACTS_RESTRICTION_TEMPLATE = (
    "(contactcompanynumber!='null' and electronicmailaddress!='null') and "
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
        window_start = date.today() - timedelta(days=SYNC_WINDOW_DAYS)
        restriction = ACTIVE_CUSTOMERS_RESTRICTION_TEMPLATE.format(
            window_start=(
                f"date({window_start.year},{window_start.month},{window_start.day})"
            )
        )
        return await self._filter_records(
            container="customercard",
            restriction=restriction,
            fields=CUSTOMER_CARD_FIELDS,
            limit=5000,
            stage="customer_discovery",
        )

    async def discover_contact_persons(self) -> list[dict[str, Any]]:
        """Read contact persons with a company and email changed since yesterday."""
        window_start = date.today() - timedelta(days=SYNC_WINDOW_DAYS)
        restriction = ACTIVE_CONTACTS_RESTRICTION_TEMPLATE.format(
            window_start=(
                f"date({window_start.year},{window_start.month},{window_start.day})"
            )
        )
        return await self._filter_records(
            container="contactpersons",
            restriction=restriction,
            fields=CONTACT_PERSON_FIELDS,
            limit=5000,
            stage="contact_discovery",
        )

    async def get_contacts_for_customers(
        self, customer_numbers: list[str]
    ) -> list[dict[str, Any]]:
        """Read all contact persons of newly created customers."""
        by_number: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(customer_numbers), 50):
            batch = customer_numbers[offset : offset + 50]
            clauses = [
                "(contactcompanynumber = '"
                + number.replace("'", "''")
                + "')"
                for number in batch
            ]
            records = await self._filter_records(
                container="contactpersons",
                restriction=" or ".join(clauses),
                fields=CONTACT_PERSON_FIELDS,
                limit=5000,
                stage="new_customer_contacts_lookup",
            )
            for record in records:
                number = str(record.get(CONTACT_PERSON_NUMBER_FIELD) or "").strip()
                if number:
                    by_number[number] = record
        return list(by_number.values())

    async def get_contact_persons_by_emails(
        self, emails: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Back-query full email groups without a date restriction."""
        unique_emails = list(dict.fromkeys(email.strip().lower() for email in emails))
        batches = [unique_emails[i : i + 5] for i in range(0, len(unique_emails), 5)]
        semaphore = asyncio.Semaphore(10)

        async def fetch_batch(batch: list[str]) -> list[dict[str, Any]]:
            clauses = [
                "(electronicmailaddress like '"
                + email.replace("'", "''")
                + "')"
                for email in batch
            ]
            async with semaphore:
                return await self._filter_records(
                    container="contactpersons",
                    restriction=" or ".join(clauses),
                    fields=CONTACT_PERSON_FIELDS,
                    limit=5000,
                    stage="contact_master_back_query",
                )

        results = await asyncio.gather(*(fetch_batch(batch) for batch in batches))
        by_email: dict[str, list[dict[str, Any]]] = {}
        seen: set[str] = set()
        for records in results:
            for record in records:
                number = str(record.get(CONTACT_PERSON_NUMBER_FIELD) or "").strip()
                email = str(record.get("electronicmailaddress") or "").strip().lower()
                if number and number not in seen and email in unique_emails:
                    seen.add(number)
                    by_email.setdefault(email, []).append(record)
        return by_email

    async def get_specification1_descriptions(self) -> dict[str, str]:
        """Read Specification 1 descriptions using the cached reconnect token."""
        records = await self._filter_records(
            container="specification1",
            restriction="",
            fields=SPECIFICATION1_FIELDS,
            limit=1000,
            offset=0,
            stage="specification1_lookup",
        )
        return {
            str(record.get("specification1name") or "").strip(): str(
                record.get("description") or ""
            ).strip()
            for record in records
            if str(record.get("specification1name") or "").strip()
            and str(record.get("description") or "").strip()
        }

    async def get_specification6_descriptions(self) -> dict[str, str]:
        """Read Specification 6 descriptions using the cached reconnect token."""
        records = await self._filter_records(
            container="specification6",
            restriction="",
            fields=SPECIFICATION6_FIELDS,
            limit=1000,
            offset=0,
            stage="specification6_lookup",
        )
        return {
            str(record.get("specification6name") or "").strip(): str(
                record.get("description") or ""
            ).strip()
            for record in records
            if str(record.get("specification6name") or "").strip()
            and str(record.get("description") or "").strip()
        }

    async def update_customer_sync_version(self, customer_number: str) -> dict[str, Any]:
        """Write customerremark26 from the freshly bound versionnumber + 1."""
        source_id = str(customer_number).strip()
        if not source_id:
            raise MaconomyError(
                "Maconomy customer checkpoint needs a customer number",
                stage="customer_checkpoint",
                reason="missing_customer_number",
            )

        shortname = quote(self.settings.maconomy_shortname, safe="")
        container_url = (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/customercard"
        )
        reconnect_token = await self.authenticate()
        headers = {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }

        for attempt in range(2):
            record, instance_id, bound_token = await self._bind_customer_for_checkpoint(
                container_url, headers, source_id
            )
            try:
                bound_version = int(record[VERSION_FIELD])
            except (KeyError, TypeError, ValueError) as exc:
                raise MaconomyError(
                    f"Invalid Maconomy version for customer {source_id}",
                    stage="customer_checkpoint",
                    reason="invalid_bound_version",
                ) from exc

            checkpoint_value = str(bound_version + 1)
            response = await self._checkpoint_post(
                f"{container_url}/instances/{instance_id}/data/panes/card/0",
                headers={
                    **headers,
                    "Maconomy-Concurrency-Control": bound_token,
                },
                payload={
                    "data": {CUSTOMER_SYNCED_VERSION_FIELD: checkpoint_value},
                    "offset": 0,
                    "limit": 100,
                },
                source_id=source_id,
                operation="update",
            )
            if response.status_code in (409, 412) and attempt == 0:
                continue
            if not response.is_success:
                raise self._checkpoint_status_error(response, source_id, "update")

            saved_record, _, _ = await self._bind_customer_for_checkpoint(
                container_url, headers, source_id
            )
            try:
                saved_version = int(saved_record[VERSION_FIELD])
            except (KeyError, TypeError, ValueError) as exc:
                raise MaconomyError(
                    f"Invalid saved Maconomy version for customer {source_id}",
                    stage="customer_checkpoint",
                    reason="invalid_saved_version",
                ) from exc
            if (
                saved_version != bound_version + 1
                or str(saved_record.get(CUSTOMER_SYNCED_VERSION_FIELD) or "").strip()
                != checkpoint_value
            ):
                raise MaconomyError(
                    f"Maconomy customer {source_id} checkpoint verification failed",
                    stage="customer_checkpoint",
                    reason="verification_failed",
                )
            return {
                "source_id": source_id,
                "checkpoint_field": CUSTOMER_SYNCED_VERSION_FIELD,
                "checkpoint_value": checkpoint_value,
                "versionnumber": saved_version,
                "conflict_retried": attempt > 0,
            }

        raise MaconomyError(
            f"Maconomy customer {source_id} checkpoint conflict persisted",
            stage="customer_checkpoint",
            reason="version_conflict",
        )

    async def write_contact_master_stamp(
        self, contact_person_number: str, master_number: str
    ) -> dict[str, Any]:
        """Write remark4 only when the current Contact Person has no stamp."""
        source_id = str(contact_person_number).strip()
        master = str(master_number).strip()
        if not source_id or not master:
            raise MaconomyError(
                "Contact master stamp needs contact and master numbers",
                stage="contact_master_stamp",
                reason="missing_contact_or_master_number",
            )
        shortname = quote(self.settings.maconomy_shortname, safe="")
        container_url = (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/contactpersons"
        )
        reconnect_token = await self.authenticate()
        headers = {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }

        for attempt in range(2):
            record, instance_id, bound_token = await self._bind_contact_for_writeback(
                container_url, headers, source_id
            )
            current_master = str(record.get(CONTACT_MASTER_FIELD) or "").strip()
            if current_master:
                if current_master != master:
                    raise MaconomyError(
                        f"Contact {source_id} already points to master {current_master}",
                        stage="contact_master_stamp",
                        reason="existing_master_conflict",
                    )
                return {"source_id": source_id, "master_number": master, "written": False}

            response = await self._checkpoint_post(
                f"{container_url}/instances/{instance_id}/data/panes/card/0",
                headers={**headers, "Maconomy-Concurrency-Control": bound_token},
                payload={
                    "data": {CONTACT_MASTER_FIELD: master},
                    "offset": 0,
                    "limit": 100,
                },
                source_id=source_id,
                operation="update",
                entity="contact",
            )
            if response.status_code in (409, 412) and attempt == 0:
                continue
            if not response.is_success:
                raise self._checkpoint_status_error(
                    response, source_id, "update", entity="contact"
                )

            saved, _, _ = await self._bind_contact_for_writeback(
                container_url, headers, source_id
            )
            if str(saved.get(CONTACT_MASTER_FIELD) or "").strip() != master:
                raise MaconomyError(
                    f"Contact {source_id} remark4 stamp could not be verified",
                    stage="contact_master_stamp",
                    reason="verification_failed",
                )
            return {
                "source_id": source_id,
                "master_number": master,
                "written": True,
                "conflict_retried": attempt > 0,
            }

        raise MaconomyError(
            f"Contact {source_id} master stamp conflict persisted",
            stage="contact_master_stamp",
            reason="version_conflict",
        )

    async def write_contact_sync_checkpoint(
        self, contact_person_number: str, master_number: str
    ) -> dict[str, Any]:
        """Write remark5 from the freshly bound Contact Person version + 1."""
        source_id = str(contact_person_number).strip()
        master = str(master_number).strip()
        if not source_id or not master:
            raise MaconomyError(
                "Contact checkpoint needs contact and master numbers",
                stage="contact_checkpoint",
                reason="missing_contact_or_master_number",
            )
        shortname = quote(self.settings.maconomy_shortname, safe="")
        container_url = (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/contactpersons"
        )
        reconnect_token = await self.authenticate()
        headers = {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }

        for attempt in range(2):
            record, instance_id, bound_token = await self._bind_contact_for_writeback(
                container_url, headers, source_id, stage="contact_checkpoint"
            )
            current_master = str(record.get(CONTACT_MASTER_FIELD) or "").strip()
            if current_master != master:
                raise MaconomyError(
                    f"Contact {source_id} remark4 does not match master {master}",
                    stage="contact_checkpoint",
                    reason="master_mismatch",
                )
            try:
                bound_version = int(record[VERSION_FIELD])
            except (KeyError, TypeError, ValueError) as exc:
                raise MaconomyError(
                    f"Invalid version for Contact {source_id} checkpoint",
                    stage="contact_checkpoint",
                    reason="invalid_bound_version",
                ) from exc
            checkpoint_value = str(bound_version + 1)
            response = await self._checkpoint_post(
                f"{container_url}/instances/{instance_id}/data/panes/card/0",
                headers={**headers, "Maconomy-Concurrency-Control": bound_token},
                payload={
                    "data": {CONTACT_SYNCED_VERSION_FIELD: checkpoint_value},
                    "offset": 0,
                    "limit": 100,
                },
                source_id=source_id,
                operation="update",
                entity="contact",
                stage="contact_checkpoint",
            )
            if response.status_code in (409, 412) and attempt == 0:
                continue
            if not response.is_success:
                raise self._checkpoint_status_error(
                    response,
                    source_id,
                    "update",
                    entity="contact",
                    stage="contact_checkpoint",
                )

            saved, _, _ = await self._bind_contact_for_writeback(
                container_url, headers, source_id, stage="contact_checkpoint"
            )
            try:
                saved_version = int(saved[VERSION_FIELD])
            except (KeyError, TypeError, ValueError) as exc:
                raise MaconomyError(
                    f"Invalid saved version for Contact {source_id} checkpoint",
                    stage="contact_checkpoint",
                    reason="invalid_saved_version",
                ) from exc
            if (
                saved_version != bound_version + 1
                or str(saved.get(CONTACT_SYNCED_VERSION_FIELD) or "").strip()
                != checkpoint_value
                or str(saved.get(CONTACT_MASTER_FIELD) or "").strip() != master
            ):
                raise MaconomyError(
                    f"Contact {source_id} remark5 checkpoint verification failed",
                    stage="contact_checkpoint",
                    reason="verification_failed",
                )
            return {
                "source_id": source_id,
                "checkpoint_field": CONTACT_SYNCED_VERSION_FIELD,
                "checkpoint_value": checkpoint_value,
                "versionnumber": saved_version,
                "conflict_retried": attempt > 0,
            }

        raise MaconomyError(
            f"Contact {source_id} checkpoint conflict persisted",
            stage="contact_checkpoint",
            reason="version_conflict",
        )

    async def _bind_contact_for_writeback(
        self,
        container_url: str,
        headers: dict[str, str],
        source_id: str,
        *,
        stage: str = "contact_master_stamp",
    ) -> tuple[dict[str, Any], str, str]:
        response = await self._checkpoint_post(
            f"{container_url}/instances",
            headers=headers,
            payload={
                "panes": {
                    "card": {
                        "fields": [
                            CONTACT_PERSON_NUMBER_FIELD,
                            CONTACT_MASTER_FIELD,
                            CONTACT_SYNCED_VERSION_FIELD,
                            VERSION_FIELD,
                        ]
                    }
                }
            },
            source_id=source_id,
            operation="instance",
            entity="contact",
            stage=stage,
        )
        if not response.is_success:
            raise self._checkpoint_status_error(
                response, source_id, "instance", entity="contact", stage=stage
            )
        try:
            instance_id = str(response.json()["meta"]["containerInstanceId"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyError(
                f"Invalid Contact {source_id} instance response",
                stage=stage,
                reason="invalid_instance_response",
            ) from exc
        token = (response.headers.get("Maconomy-Concurrency-Control") or "").strip()
        if not instance_id or not token:
            raise MaconomyError(
                f"Contact {source_id} instance token is missing",
                stage=stage,
                reason="missing_instance_token",
            )

        response = await self._checkpoint_post(
            f"{container_url}/instances/{instance_id}/data;"
            f"{CONTACT_PERSON_NUMBER_FIELD}={quote(source_id, safe='')}",
            headers={**headers, "Maconomy-Concurrency-Control": token},
            payload={},
            source_id=source_id,
            operation="bind",
            entity="contact",
            stage=stage,
        )
        if not response.is_success:
            raise self._checkpoint_status_error(
                response, source_id, "bind", entity="contact", stage=stage
            )
        bound_token = (
            response.headers.get("Maconomy-Concurrency-Control") or ""
        ).strip()
        if not bound_token:
            raise MaconomyError(
                f"Contact {source_id} bind token is missing",
                stage=stage,
                reason="missing_bind_token",
            )
        try:
            records = response.json()["panes"]["card"]["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyError(
                f"Invalid Contact {source_id} bind response",
                stage=stage,
                reason="invalid_bind_response",
            ) from exc
        if not isinstance(records, list):
            raise MaconomyError(
                f"Invalid Contact {source_id} bind records",
                stage=stage,
                reason="invalid_bind_records",
            )
        matching = [
            item["data"]
            for item in records
            if isinstance(item, dict)
            and isinstance(item.get("data"), dict)
            and str(item["data"].get(CONTACT_PERSON_NUMBER_FIELD) or "").strip()
            == source_id
        ]
        if len(matching) != 1:
            raise MaconomyError(
                f"Contact {source_id} was not uniquely found for writeback",
                stage=stage,
                reason="contact_not_found",
            )
        return matching[0], instance_id, bound_token

    async def _bind_customer_for_checkpoint(
        self,
        container_url: str,
        headers: dict[str, str],
        source_id: str,
    ) -> tuple[dict[str, Any], str, str]:
        response = await self._checkpoint_post(
            f"{container_url}/instances",
            headers=headers,
            payload={
                "panes": {
                    "card": {
                        "fields": [
                            CUSTOMER_NUMBER_FIELD,
                            CUSTOMER_SYNCED_VERSION_FIELD,
                            VERSION_FIELD,
                        ]
                    }
                }
            },
            source_id=source_id,
            operation="instance",
        )
        if not response.is_success:
            raise self._checkpoint_status_error(response, source_id, "instance")
        try:
            instance_id = str(response.json()["meta"]["containerInstanceId"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyError(
                f"Invalid Maconomy customer {source_id} instance response",
                stage="customer_checkpoint",
                reason="invalid_instance_response",
            ) from exc
        concurrency_token = (
            response.headers.get("Maconomy-Concurrency-Control") or ""
        ).strip()
        if not instance_id or not concurrency_token:
            raise MaconomyError(
                f"Maconomy customer {source_id} instance token is missing",
                stage="customer_checkpoint",
                reason="missing_instance_token",
            )

        response = await self._checkpoint_post(
            f"{container_url}/instances/{instance_id}/data;"
            f"{CUSTOMER_NUMBER_FIELD}={quote(source_id, safe='')}",
            headers={
                **headers,
                "Maconomy-Concurrency-Control": concurrency_token,
            },
            payload={},
            source_id=source_id,
            operation="bind",
        )
        if not response.is_success:
            raise self._checkpoint_status_error(response, source_id, "bind")
        bound_token = (
            response.headers.get("Maconomy-Concurrency-Control") or ""
        ).strip()
        if not bound_token:
            raise MaconomyError(
                f"Maconomy customer {source_id} bind token is missing",
                stage="customer_checkpoint",
                reason="missing_bind_token",
            )
        try:
            records = response.json()["panes"]["card"]["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyError(
                f"Invalid Maconomy customer {source_id} bind response",
                stage="customer_checkpoint",
                reason="invalid_bind_response",
            ) from exc
        if not isinstance(records, list):
            raise MaconomyError(
                f"Invalid Maconomy customer {source_id} bind records",
                stage="customer_checkpoint",
                reason="invalid_bind_records",
            )
        matching = [
            item["data"]
            for item in records
            if isinstance(item, dict)
            and isinstance(item.get("data"), dict)
            and str(item["data"].get(CUSTOMER_NUMBER_FIELD) or "").strip()
            == source_id
        ]
        if len(matching) != 1:
            raise MaconomyError(
                f"Maconomy customer {source_id} was not uniquely found for writeback",
                stage="customer_checkpoint",
                reason="customer_not_found",
            )
        return matching[0], instance_id, bound_token

    async def _checkpoint_post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        source_id: str,
        operation: str,
        entity: str = "customer",
        stage: str | None = None,
    ) -> httpx.Response:
        try:
            return await self.client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise MaconomyError(
                f"Maconomy {entity} {source_id} {operation} request failed",
                stage=stage or (
                    "customer_checkpoint" if entity == "customer" else "contact_master_stamp"
                ),
                reason=(
                    "timeout" if isinstance(exc, httpx.TimeoutException) else "request_error"
                ),
            ) from exc

    @staticmethod
    def _checkpoint_status_error(
        response: httpx.Response,
        source_id: str,
        operation: str,
        *,
        entity: str = "customer",
        stage: str | None = None,
    ) -> MaconomyError:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        upstream_message = None
        if isinstance(payload, dict):
            upstream_message = str(
                payload.get("message") or payload.get("error") or ""
            ).strip()[:1000] or None
        return MaconomyError(
            f"Maconomy {entity} {source_id} {operation} was rejected",
            stage=stage or (
                "customer_checkpoint" if entity == "customer" else "contact_master_stamp"
            ),
            reason=(
                "version_conflict"
                if response.status_code in (409, 412)
                else f"{operation}_http_status"
            ),
            upstream_status=response.status_code,
            upstream_message=upstream_message,
        )

    @staticmethod
    def _filter_response_message(response: httpx.Response) -> str | None:
        """Keep a short Maconomy error message without logging the full body."""
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        for field in ("message", "errorMessage", "error", "detail"):
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()[:1000]
        return None

    async def _filter_records(
        self,
        *,
        container: str,
        restriction: str,
        fields: list[str],
        limit: int,
        stage: str,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        reconnect_token = await self.authenticate()
        shortname = quote(self.settings.maconomy_shortname, safe="")
        url = (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/{container}/filter"
        )
        payload: dict[str, Any] = {
            "restriction": restriction,
            "fields": fields,
            "limit": limit,
        }
        if offset is not None:
            payload["offset"] = offset
        try:
            response = await self.client.post(
                url,
                headers={
                    "Accept": CONTAINER_ACCEPT,
                    "Content-Type": CONTAINER_CONTENT_TYPE,
                    "Authorization": f"X-Reconnect {reconnect_token}",
                },
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyError(
                f"Maconomy {container} filter request failed",
                stage=stage,
                reason=(
                    "http_status"
                    if isinstance(exc, httpx.HTTPStatusError)
                    else "timeout"
                    if isinstance(exc, httpx.TimeoutException)
                    else "request_error"
                ),
                upstream_status=(
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                ),
                upstream_message=(
                    self._filter_response_message(exc.response)
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                ),
            ) from exc

        try:
            records = response.json()["panes"]["filter"]["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyError(
                f"Invalid Maconomy {container} filter response: missing records",
                stage=stage,
                reason="invalid_response",
                upstream_status=response.status_code,
            ) from exc
        if not isinstance(records, list):
            raise MaconomyError(
                f"Invalid Maconomy {container} filter response: records is not a list",
                stage=stage,
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

    @staticmethod
    def classify_contact_persons(
        contacts: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Keep contacts whose versionnumber is newer than remark5."""
        new_contacts: list[dict[str, Any]] = []
        updated_contacts: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        seen_numbers: set[str] = set()

        for contact in contacts:
            contact_number = str(
                contact.get(CONTACT_PERSON_NUMBER_FIELD) or ""
            ).strip()
            if not contact_number:
                skipped.append(
                    {"source_id": None, "reason": "missing contactpersonnumber"}
                )
                continue
            if contact_number in seen_numbers:
                skipped.append(
                    {"source_id": contact_number, "reason": "duplicate contactpersonnumber"}
                )
                continue
            seen_numbers.add(contact_number)

            version = contact.get(VERSION_FIELD)
            version_text = str(version).strip() if version is not None else ""
            try:
                current_version = int(version_text)
            except ValueError:
                skipped.append(
                    {"source_id": contact_number, "reason": "invalid versionnumber"}
                )
                continue

            synced_version = contact.get(CONTACT_SYNCED_VERSION_FIELD)
            synced_text = (
                str(synced_version).strip() if synced_version is not None else ""
            )
            if not synced_text:
                new_contacts.append({**contact, "action": "create"})
                continue
            try:
                previous_version = int(synced_text)
            except ValueError:
                skipped.append(
                    {"source_id": contact_number, "reason": "invalid remark5"}
                )
                continue
            if current_version > previous_version:
                updated_contacts.append({**contact, "action": "update"})
            elif current_version < previous_version:
                skipped.append(
                    {
                        "source_id": contact_number,
                        "reason": "remark5 exceeds versionnumber",
                    }
                )

        return {
            "new_contact_persons": new_contacts,
            "updated_contact_persons": updated_contacts,
            "skipped": skipped,
        }
