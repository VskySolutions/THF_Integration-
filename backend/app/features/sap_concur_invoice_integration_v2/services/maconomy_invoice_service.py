"""Create, submit, and approve invoices on one Maconomy instance per invoice."""

import base64
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.features.sap_concur_invoice_integration_v2.constants import InvoiceActionStatus
from app.features.sap_concur_invoice_integration_v2.mappers.maconomy_invoice_mapper import (
    map_concur_invoice_to_maconomy_invoice_card,
)
from app.features.sap_concur_invoice_integration_v2.mappers.maconomy_line_mapper import (
    build_jobtasks_instance_payload,
    build_vendor_invoice_allocation_instance_payload,
    build_vendor_invoice_table_init_payload,
    line_value,
    map_concur_invoice_line_to_allocation_row,
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


class MaconomyInvoiceServiceError(Exception):
    pass


class AllocationLineValidationError(ValueError):
    """An allocation validation failure with a machine-readable reason."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def _action_failure(exc: MaconomyInvoiceServiceError | httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code >= 500:
            return (
                f"Maconomy returned HTTP {exc.response.status_code}. "
                "Verify the invoice in Maconomy."
            )
        return f"Maconomy returned HTTP {exc.response.status_code}."
    if isinstance(exc, httpx.RequestError):
        return "The request outcome is unknown. Verify the invoice in Maconomy."
    return str(exc)


def _response_object(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        result = response.json()
    except ValueError as exc:
        raise MaconomyInvoiceServiceError(
            f"Invalid Maconomy {operation} response"
        ) from exc
    if not isinstance(result, dict):
        raise MaconomyInvoiceServiceError(f"Invalid Maconomy {operation} response")
    return result


def _response_field(
    result: dict[str, Any], pane_name: str, field: str
) -> Iterator[str]:
    panes = result.get("panes")
    pane = panes.get(pane_name) if isinstance(panes, dict) else None
    records = pane.get("records") if isinstance(pane, dict) else None
    if isinstance(records, dict):
        records = [records]
    if isinstance(records, list):
        ordered = reversed(records) if pane_name == "table" else records
        for record in ordered:
            data = record.get("data") if isinstance(record, dict) else None
            if isinstance(data, dict) and (value := _identifier(data.get(field))):
                yield value
    data = result.get("data")
    if isinstance(data, dict) and (value := _identifier(data.get(field))):
        yield value
    if value := _identifier(result.get(field)):
        yield value


def _identifier(value: Any) -> str:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return str(value).strip()
    return ""


def _card_line_number(result: dict[str, Any]) -> int | None:
    for value in _response_field(result, "card", "linenumber"):
        try:
            return int(value)
        except ValueError:
            continue
    return None


class MaconomyInvoiceService:
    """Read Maconomy references and process invoice cards and allocations."""

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
            raise MaconomyInvoiceServiceError("Maconomy authentication failed")
        return token

    @staticmethod
    def _container_headers(reconnect_token: str) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }

    @staticmethod
    def _get_concurrency_token(response: httpx.Response) -> str:
        concurrency_token = response.headers.get(
            "Maconomy-Concurrency-Control",
            "",
        ).strip()

        try:
            return str(uuid.UUID(concurrency_token))

        except (TypeError, ValueError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy concurrency token"
            ) from exc

    def _vendor_invoice_allocation_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/{shortname}/vendorinvoiceallocation"
        )

    def _show_vendor_invoices_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/{shortname}/showvendorinvoices"
        )

    def _vendorcard_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/{shortname}/vendorcard"
        )

    def _entities_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/{shortname}/entities"
        )

    def _jobtasks_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/{shortname}/jobtasks"
        )

    @staticmethod
    def _build_remark5_restriction(invoice_ids: list[str]) -> str:
        """Escape invoice IDs for the Maconomy remark5 filter."""
        escaped = [
            str(v).strip().replace("'", "''")
            for v in invoice_ids
            if v is not None and str(v).strip()
        ]
        return " or ".join(f"remark5 = '{v}'" for v in escaped)

    async def _get_maconomy_invoices_by_ids(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        invoice_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch Maconomy matches for the supplied Concur invoice IDs."""
        payload = {
            "restriction": self._build_remark5_restriction(invoice_ids),
            "fields": [
                "amountcurrency",
                "currency",
                "entrydate",
                "entrytext",
                "exchangerate",
                "fixedexchangerateforpayment",
                "instancekey",
                "invoicenumber",
                "journalnumber",
                "linenumber",
                "name1",
                "transactionnumber",
                "vendornumber",
                "remark5",
            ],
            "limit": 500,
        }
        response = await client.post(
            f"{self._show_vendor_invoices_url()}/filter",
            headers=self._container_headers(reconnect_token),
            json=payload,
        )
        response.raise_for_status()

        try:
            records = response.json()["panes"]["filter"]["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid showvendorinvoices response"
            ) from exc

        existing: list[dict[str, Any]] = []
        for record in records:
            if not (
                isinstance(record, dict)
                and isinstance(record.get("data"), dict)
            ):
                continue
            data = record["data"]
            sap_invoice_id = str(data.get("remark5") or "").strip()
            if not sap_invoice_id:
                continue
            existing.append(
                {
                    "sap_invoice_id": sap_invoice_id,
                    "invoicenumber": data.get("invoicenumber"),
                    "journalnumber": data.get("journalnumber"),
                    "linenumber": data.get("linenumber"),
                    "instancekey": data.get("instancekey"),
                }
            )

        return existing

    async def get_existing_invoice_ids(
        self, invoice_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Find invoices previously synced to Maconomy."""
        if not any(v is not None and str(v).strip() for v in invoice_ids):
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)
                existing = await self._get_maconomy_invoices_by_ids(
                    client, reconnect_token, invoice_ids
                )
        except httpx.HTTPError as exc:
            raise MaconomyInvoiceServiceError(
                f"Maconomy showvendorinvoices request failed: {exc}"
            ) from exc
        return existing

    async def get_all_vendor_numbers(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> set[str]:
        """Load case-folded vendor numbers with offset pagination."""
        url = f"{self._vendorcard_url()}/filter"
        limit = 1000
        offset = 0
        pages = 0
        vendor_numbers: set[str] = set()

        while True:
            if pages >= 100:
                raise MaconomyInvoiceServiceError(
                    "Maconomy vendor reference retrieval exceeded the "
                    "maximum page ceiling of 100"
                )
            payload = {
                "fields": ["vendornumber"],
                "limit": limit,
                "offset": offset,
            }
            try:
                response = await client.post(
                    url,
                    headers=self._container_headers(reconnect_token),
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise MaconomyInvoiceServiceError(
                    "Maconomy vendor reference request failed"
                ) from exc
            pages += 1

            try:
                pane = response.json()["panes"]["filter"]
                meta = pane["meta"]
                records = pane["records"]
            except (KeyError, TypeError, ValueError) as exc:
                raise MaconomyInvoiceServiceError(
                    "Invalid Maconomy vendor filter response"
                ) from exc
            if (
                not isinstance(meta, dict)
                or not isinstance(records, list)
                or not all(isinstance(record, dict) for record in records)
            ):
                raise MaconomyInvoiceServiceError(
                    "Invalid Maconomy vendor filter response"
                )

            row_count = meta.get("rowCount")
            row_offset = meta.get("rowOffset")
            if (
                isinstance(row_count, bool)
                or not isinstance(row_count, int)
                or row_count != len(records)
                or (row_offset is not None and row_offset != offset)
            ):
                raise MaconomyInvoiceServiceError(
                    "Invalid Maconomy vendor filter response"
                )

            for record in records:
                data = record.get("data")
                if not isinstance(data, dict):
                    raise MaconomyInvoiceServiceError(
                        "Invalid Maconomy vendor filter response"
                    )
                vendor_number = str(data.get("vendornumber") or "").strip()
                if vendor_number:
                    vendor_numbers.add(vendor_number.casefold())

            if len(records) < limit:
                break
            offset += limit

        return vendor_numbers

    async def get_all_entity_names(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> set[str]:
        """Load case-folded names for active Maconomy entities."""
        url = f"{self._entities_url()}/filter"
        limit = 1000
        offset = 0
        pages = 0
        entity_names: set[str] = set()

        while True:
            if pages >= 100:
                raise MaconomyInvoiceServiceError(
                    "Maconomy entity reference retrieval exceeded the "
                    "maximum page ceiling of 100"
                )
            payload = {
                "fields": ["entityname", "description", "blocked"],
                "limit": limit,
                "offset": offset,
            }
            try:
                response = await client.post(
                    url,
                    headers=self._container_headers(reconnect_token),
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise MaconomyInvoiceServiceError(
                    "Maconomy entity reference request failed"
                ) from exc
            pages += 1

            try:
                pane = response.json()["panes"]["filter"]
                records = pane["records"]
            except (KeyError, TypeError, ValueError) as exc:
                raise MaconomyInvoiceServiceError(
                    "Invalid Maconomy entities filter response"
                ) from exc
            if (
                not isinstance(records, list)
                or not all(isinstance(record, dict) for record in records)
            ):
                raise MaconomyInvoiceServiceError(
                    "Invalid Maconomy entities filter response"
                )

            for record in records:
                data = record.get("data")
                if not isinstance(data, dict):
                    raise MaconomyInvoiceServiceError(
                        "Invalid Maconomy entities filter response"
                    )
                if data.get("blocked") is True:
                    continue
                entity_name = str(data.get("entityname") or "").strip()
                if entity_name:
                    entity_names.add(entity_name.casefold())

            if len(records) < limit:
                break
            offset += limit

        return entity_names

    async def get_engagement_tasks(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        engagement: str,
    ) -> set[str] | None:
        """Return case-folded task names, or None for an unknown engagement."""
        try:
            response = await client.post(
                f"{self._jobtasks_url()}/instances",
                headers=self._container_headers(reconnect_token),
                json=build_jobtasks_instance_payload(),
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyInvoiceServiceError(
                "Maconomy jobtasks instance request failed"
            ) from exc

        try:
            instance_id = str(
                uuid.UUID(response.json()["meta"]["containerInstanceId"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy jobtasks instance response"
            ) from exc
        concurrency_token = self._get_concurrency_token(response)

        url = (
            f"{self._jobtasks_url()}/instances/"
            f"{instance_id}/data;jobnumber="
            f"{quote(str(engagement), safe='')}"
        )
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token
        try:
            response = await client.post(
                url,
                headers=headers,
                json={"limit": 100, "offset": 0},
            )
        except httpx.HTTPError as exc:
            raise MaconomyInvoiceServiceError(
                "Maconomy jobtasks data request failed"
            ) from exc

        if response.status_code == 204:
            return None

        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyInvoiceServiceError(
                "Maconomy jobtasks data request failed"
            ) from exc

        try:
            records = response.json()["panes"]["table"]["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy jobtasks data response"
            ) from exc
        if (
            not isinstance(records, list)
            or not all(isinstance(record, dict) for record in records)
        ):
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy jobtasks data response"
            )

        task_names: set[str] = set()
        for record in records:
            data = record.get("data")
            if not isinstance(data, dict):
                raise MaconomyInvoiceServiceError(
                    "Invalid Maconomy jobtasks data response"
                )
            raw_task_name = str(data.get("taskname") or "").strip()
            if raw_task_name:
                task_names.add(raw_task_name.casefold())
        return task_names

    async def create_invoices(
        self, entries: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            reconnect_token = await self._get_reconnect_token(client)
            vendor_numbers = await self.get_all_vendor_numbers(client, reconnect_token)
            entity_names = await self.get_all_entity_names(client, reconnect_token)

            results = []
            for entry in entries:
                result = await self._create_invoice(
                    client, reconnect_token, vendor_numbers, entity_names, entry
                )
                results.append(result)
            return results

    async def _create_invoice(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        vendor_numbers: set[str],
        entity_names: set[str],
        entry: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        invoice = entry["invoice"]
        invoice_id = str(
            invoice.get("PaymentRequestId") or invoice.get("ID") or ""
        ).strip()
        line_items = entry["lineItems"]

        try:
            payload = map_concur_invoice_to_maconomy_invoice_card(invoice)
            vendor_number = payload["data"]["vendornumber"]
            if vendor_number.casefold() not in vendor_numbers:
                raise ValueError(f"Vendor {vendor_number} not found in Maconomy")

            instance_url, concurrency_token = await self._open_invoice_instance(
                client, reconnect_token
            )
            card_url = f"{instance_url}/data/panes/card"
            initialized = await self._post_pane(
                client, reconnect_token, concurrency_token, f"{card_url}/init", {}
            )
            concurrency_token = self._get_concurrency_token(initialized)
            created = await self._post_pane(
                client,
                reconnect_token,
                concurrency_token,
                card_url,
                payload,
            )
            card = _response_object(created, "invoice card")
            journalnumber = next(_response_field(card, "card", "journalnumber"), "")
            if not journalnumber:
                raise MaconomyInvoiceServiceError(
                    "journalnumber missing from the Maconomy invoice card response"
                )
        except (ValueError, MaconomyInvoiceServiceError, httpx.HTTPError) as exc:
            return {
                "invoice_id": invoice_id,
                "status": "FAILED",
                "message": str(exc),
                "submission": {
                    "status": InvoiceActionStatus.SKIPPED.value,
                    "message": "Invoice creation failed.",
                },
                "approval": {
                    "status": InvoiceActionStatus.SKIPPED.value,
                    "message": "Invoice creation failed.",
                },
            }, []

        invoice_number = _card_line_number(card)
        result = {
            "invoice_id": invoice_id,
            "status": "SUCCESS",
            "journalnumber": journalnumber,
            "maconomy_invoice_number": invoice_number,
            "result": card,
        }
        if invoice_number is None:
            result["warning"] = (
                "Missing or invalid linenumber in the Maconomy invoice card response"
            )

        lines = []
        last_write = created
        if line_items:
            lines, last_write = await self._create_allocation_lines(
                client,
                reconnect_token,
                instance_url,
                created,
                invoice_id,
                line_items,
                entity_names,
            )
        if any(line["status"] == "FAILED" for line in lines):
            result.update(
                submission={
                    "status": InvoiceActionStatus.SKIPPED.value,
                    "message": "One or more allocation lines failed.",
                },
                approval={
                    "status": InvoiceActionStatus.SKIPPED.value,
                    "message": "One or more allocation lines failed.",
                },
            )
        else:
            result.update(
                await self._submit_and_approve(
                    client, reconnect_token, card_url, last_write
                )
            )
        return result, lines

    async def _submit_and_approve(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        card_url: str,
        last_write: httpx.Response,
    ) -> dict[str, dict[str, str]]:
        action_url = f"{card_url}/0/action;name="
        payload = {"offset": 0, "limit": 100}
        try:
            submitted = await self._post_pane(
                client,
                reconnect_token,
                self._get_concurrency_token(last_write),
                f"{action_url}submitforapproval",
                payload,
            )
        except (MaconomyInvoiceServiceError, httpx.HTTPError) as exc:
            return {
                "submission": {
                    "status": InvoiceActionStatus.FAILED.value,
                    "message": _action_failure(exc),
                },
                "approval": {
                    "status": InvoiceActionStatus.SKIPPED.value,
                    "message": "Invoice submission failed.",
                },
            }

        submission = {
            "status": InvoiceActionStatus.SUCCESS.value,
            "message": "Invoice submitted for approval.",
        }
        try:
            await self._post_pane(
                client,
                reconnect_token,
                self._get_concurrency_token(submitted),
                f"{action_url}approveforposting",
                payload,
            )
        except (MaconomyInvoiceServiceError, httpx.HTTPError) as exc:
            approval = {
                "status": InvoiceActionStatus.FAILED.value,
                "message": _action_failure(exc),
            }
        else:
            approval = {
                "status": InvoiceActionStatus.SUCCESS.value,
                "message": "Invoice approved for posting.",
            }
        return {"submission": submission, "approval": approval}

    async def _open_invoice_instance(
        self, client: httpx.AsyncClient, reconnect_token: str
    ) -> tuple[str, str]:
        instances_url = f"{self._vendor_invoice_allocation_url()}/instances"
        response = await client.post(
            instances_url,
            headers=self._container_headers(reconnect_token),
            json=build_vendor_invoice_allocation_instance_payload(),
        )
        response.raise_for_status()
        result = _response_object(response, "invoice allocation instance")
        try:
            instance_id = uuid.UUID(result["meta"]["containerInstanceId"])
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy invoice allocation instance ID"
            ) from exc
        return f"{instances_url}/{instance_id}", self._get_concurrency_token(response)

    async def _post_pane(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        concurrency_token: str,
        url: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token
        response = await client.post(url, headers=headers, json=payload)
        print(f"POST {url} response: {response.status_code} {response.text}")
        response.raise_for_status()
        return response

    async def _create_allocation_lines(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_url: str,
        card_response: httpx.Response,
        invoice_id: str,
        line_items: list[dict[str, Any]],
        entity_names: set[str],
    ) -> tuple[list[dict[str, Any]], httpx.Response]:
        table_url = f"{instance_url}/data/panes/table"
        blocked_reason = None
        concurrency_token = ""
        last_write = card_response
        try:
            initialized = await self._post_pane(
                client,
                reconnect_token,
                self._get_concurrency_token(card_response),
                f"{table_url}/init",
                build_vendor_invoice_table_init_payload(),
            )
            concurrency_token = self._get_concurrency_token(initialized)
        except (MaconomyInvoiceServiceError, httpx.HTTPError) as exc:
            blocked_reason = f"Could not initialize allocation table: {exc}"

        lines = []
        engagement_tasks: dict[str, set[str] | None] = {}
        for index, line in enumerate(line_items):
            outcome = {"invoice_id": invoice_id, "line_index": index}
            if blocked_reason is not None:
                lines.append({**outcome, "status": "FAILED", "message": blocked_reason})
                continue

            try:
                await self._validate_line(
                    client, reconnect_token, line, entity_names, engagement_tasks
                )
                payload = map_concur_invoice_line_to_allocation_row(line)
                response = await self._post_pane(
                    client, reconnect_token, concurrency_token, table_url, payload
                )
                last_write = response
                if index + 1 < len(line_items):
                    try:
                        concurrency_token = self._get_concurrency_token(response)
                    except MaconomyInvoiceServiceError as exc:
                        blocked_reason = str(exc)
                result = _response_object(response, "invoice allocation row")
            except AllocationLineValidationError as exc:
                lines.append(
                    {
                        **outcome,
                        "status": "FAILED",
                        "message": str(exc),
                        "reason": exc.reason,
                    }
                )
            except httpx.RequestError as exc:
                blocked_reason = f"Allocation row request outcome is unknown: {exc}"
                lines.append({**outcome, "status": "FAILED", "message": blocked_reason})
            except (ValueError, MaconomyInvoiceServiceError, httpx.HTTPError) as exc:
                lines.append({**outcome, "status": "FAILED", "message": str(exc)})
            else:
                lines.append(
                    {
                        **outcome,
                        "status": "SUCCESS",
                        "maconomy_line_number": next(
                            _response_field(result, "table", "linenumber"), None
                        ),
                        "result": result,
                    }
                )
        return lines, last_write

    async def _validate_line(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        line: dict[str, Any],
        entity_names: set[str],
        engagement_tasks: dict[str, set[str] | None],
    ) -> None:
        if not isinstance(line, dict):
            raise ValueError("Invalid Concur invoice line")

        engagement = line_value(line, "Custom10", "Engagement")
        if engagement:
            key = engagement.casefold()
            if key not in engagement_tasks:
                engagement_tasks[key] = await self.get_engagement_tasks(
                    client, reconnect_token, engagement
                )
            tasks = engagement_tasks[key]
            if tasks is None:
                raise AllocationLineValidationError(
                    f"Engagement {engagement} not found in Maconomy",
                    "ENGAGEMENT_NOT_FOUND",
                )
            task = line_value(line, "Custom11", "Task")
            if task and task.casefold() not in tasks:
                raise AllocationLineValidationError(
                    f"Task {task} not found in Maconomy for engagement {engagement}",
                    "TASK_NOT_FOUND",
                )

        department = line_value(line, "Department", "Custom2")
        if department and department.casefold() not in entity_names:
            raise AllocationLineValidationError(
                f"Department {department} not found in Maconomy", "DEPARTMENT_NOT_FOUND"
            )
