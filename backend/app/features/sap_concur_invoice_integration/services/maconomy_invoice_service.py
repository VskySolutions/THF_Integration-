"""Maconomy journal + invoice-row creation (Req[#21], Phase 3 corrected).

Sequence on ONE container instance (FR-12, WO[#21.9]): retrieve
instance -> init card -> create card (STATIC journal payload) ->
init table -> one dynamically mapped invoice row per SAP Concur
invoice (CurrencyCode/InvoiceNumber/InvoiceDate). Maconomy auth,
container headers, and the concurrency-token chain are copied as-is
from `sap_concur_integration/services/maconomy_services.py`
(Reconnect-token Basic auth) per requirement FR-2/FR-9.
"""

import base64
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.features.sap_concur_invoice_integration.mappers import (
    build_vendor_invoice_allocation_instance_payload,
    build_vendor_invoice_instance_payload,
    build_vendor_invoice_table_init_payload,
    map_concur_invoice_line_to_allocation_row,
    map_concur_invoice_to_maconomy_invoice_row,
    map_concur_invoice_to_maconomy_vendor_invoice,
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


class MaconomyInvoiceService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    # Auth copied as-is from sap_concur_integration MaconomyService.
    async def _get_reconnect_token(self, client: httpx.AsyncClient) -> str:
        # return "NTE2NGM2NzYtMTdiNC00NDcyLTliNGUtMWVjODU4MzM5ODI3:M2M1NTM2ODctZWRiZi00MjFjLThhMGQtY2EzNDUyOTA1YjMyHzYyZjMzNTAxOThmZjRiMDE4NmQyMDQ1ZWQ3MDZlYjUzHzEwHzE3OTQzMTUzMTc4MjAfUGFzc3dvcmRMb2dpbh5XZWJMb2dpbh9vRFnTwZEY6gzzlY/E5WD3"
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

    def _vendor_invoice_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/{shortname}/vendorinvoices"
        )

    def _vendor_invoice_allocation_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/{shortname}/vendorinvoiceallocation"
        )

    async def _retrieve_vendor_invoice_instance(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> tuple[str, str]:
        url = f"{self._vendor_invoice_url()}/instances"
        payload = build_vendor_invoice_instance_payload()

        print("======= _retrieve_vendor_invoice_instance ==========")
        response = await client.post(
            url,
            headers=self._container_headers(reconnect_token),
            json=payload,
        )
        response.raise_for_status()

        try:
            instance_id = response.json()["meta"]["containerInstanceId"]
            instance_id = str(uuid.UUID(instance_id))

        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy vendor invoice instance response"
            ) from exc

        concurrency_token = self._get_concurrency_token(response)

        return instance_id, concurrency_token

    async def _initialize_vendor_invoice_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
    ) -> tuple[dict[str, Any], str]:
        url = (
            f"{self._vendor_invoice_url()}/instances/"
            f"{instance_id}/data/panes/card/init"
        )

        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token
        print("========= _initialize_vendor_invoice_card =========")
        response = await client.post(
            url,
            headers=headers,
            json={},
        )

        response.raise_for_status()

        try:
            initialized_data = response.json()["data"]

        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy vendor invoice initialization response"
            ) from exc

        if not isinstance(initialized_data, dict):
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy vendor invoice initialization response"
            )

        new_concurrency_token = self._get_concurrency_token(response)
        print("Vendor invoice card initialized!")
        return dict(initialized_data), new_concurrency_token

    async def _initialize_vendor_invoice_table(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
    ) -> tuple[dict[str, Any], str]:
        url = (
            f"{self._vendor_invoice_url()}/instances/"
            f"{instance_id}/data/panes/table/init"
        )

        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token
        payload = build_vendor_invoice_table_init_payload()
        print("========= _initialize_vendor_invoice_table =========")
        response = await client.post(
            url,
            headers=headers,
            json=payload,
        )

        response.raise_for_status()

        try:
            initialized_data = response.json()["data"]

        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy invoice table initialization response"
            ) from exc

        if not isinstance(initialized_data, dict):
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy invoice table initialization response"
            )

        new_concurrency_token = self._get_concurrency_token(response)
        print("Vendor invoice table initialized!")
        return dict(initialized_data), new_concurrency_token

    @staticmethod
    def _extract_row_line_number(row_result: dict[str, Any]) -> int | None:
        """Line number of ONE created invoice row, from its response.

        User 2026-11-10: **the invoice-row response returns
        ``linenumber``** (Maconomy's own link template
        ``.../data;linenumber={1};journalnumber={0}`` corroborates).

        Paths (first non-empty/None-aware):
        1. **PRIMARY — live-proven table-POST shape** (the expense
           flow reads it exactly this way, ``maconomy_services.py``
           ~L1147-1157): ``panes -> table -> records -> data ->
           linenumber`` (records as list: scanned LAST-to-FIRST for
           the first non-empty value — the created row is the newest
           record; records as dict: used directly);
        2. ``data.linenumber`` -> root ``linenumber``;
        3. the earlier ``data.journallinenumber`` / root
           ``journallinenumber`` fallbacks -> ``None``.

        The value feeds every allocation line of that invoice
        (``journallinenumber`` in the batch/payload — the batch key
        name is unchanged, only the RESPONSE field is ``linenumber``).
        Non-numeric values collapse to ``None`` (the line mapper then
        raises a ValueError naming the missing linkage field); the raw
        bodies printed by ``[invoice-api]`` confirm the live path
        (R-12).
        """
        data = row_result.get("data") if isinstance(row_result, dict) else None

        def _first_not_empty(*candidates: Any) -> Any:
            for candidate in candidates:
                if candidate is not None and str(candidate).strip() != "":
                    return candidate
            return None

        # PRIMARY: panes.table.records[].data.linenumber (live shape).
        pane_ln: Any = None
        panes = row_result.get("panes") if isinstance(row_result, dict) else None
        if isinstance(panes, dict):
            table = panes.get("table")
            if isinstance(table, dict):
                records = table.get("records")
                if isinstance(records, dict):
                    rec_data = records.get("data")
                    if isinstance(rec_data, dict):
                        pane_ln = rec_data.get("linenumber")
                elif isinstance(records, list):
                    for record in reversed(records):
                        if not isinstance(record, dict):
                            continue
                        rec_data = record.get("data")
                        if not isinstance(rec_data, dict):
                            continue
                        candidate = rec_data.get("linenumber")
                        if (
                            candidate is not None
                            and str(candidate).strip() != ""
                        ):
                            pane_ln = candidate
                            break

        raw = _first_not_empty(
            pane_ln,
            data.get("linenumber") if isinstance(data, dict) else None,
            row_result.get("linenumber"),
            data.get("journallinenumber") if isinstance(data, dict) else None,
            row_result.get("journallinenumber"),
        )
        if raw is None:
            return None

        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_journal_number(journal_payload: dict[str, Any]) -> str:
        """Journal number from the card-create response.

        **PRIMARY path (user 2026-11-10, WO[#27.8] Step 1):**
        ``panes -> card -> records -> data -> journalnumber`` — every hop
        guarded; ``records`` may be a list (first record whose
        ``data.journalnumber`` is non-empty wins) or a dict. Fallbacks:
        top-level ``data.journalnumber`` -> root ``journalnumber`` ->
        ``""`` (an empty value short-circuits the line phase —
        ``line_error: "journalnumber missing from journal response"``).
        """
        panes = journal_payload.get("panes")
        card = panes.get("card") if isinstance(panes, dict) else None
        records = card.get("records") if isinstance(card, dict) else None

        candidates: list[Any] = []
        if isinstance(records, list):
            for record in records:
                data = record.get("data") if isinstance(record, dict) else None
                if isinstance(data, dict):
                    candidates.append(data.get("journalnumber"))
        elif isinstance(records, dict):
            data = records.get("data")
            if isinstance(data, dict):
                candidates.append(data.get("journalnumber"))

        top_data = journal_payload.get("data")
        if isinstance(top_data, dict):
            candidates.append(top_data.get("journalnumber"))
        candidates.append(journal_payload.get("journalnumber"))

        for candidate in candidates:
            if candidate is not None and str(candidate).strip():
                return str(candidate).strip()
        return ""

    async def create_journal_with_invoices(
        self,
        entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create ONE journal + each invoice AND its lines, interleaved.

        **INTERLEAVED FLOW (user 2026-11-10, WO[#27.8]; supersedes
        WO[#27.7] D-1 batch model)** — sequence:

        retrieve instance -> init card -> create card (STATIC journal
        payload, Q-1 ``journalnumber`` extracted via
        ``_extract_journal_number``) -> init table -> **for each entry**
        (FR-12): dynamic row map + POST table row -> **immediately** the
        SAME invoice's allocation lines on its own
        ``vendorinvoiceallocation`` instance (``_create_lines_for_invoice``)
        -> next invoice's row -> its lines -> ... So in Maconomy the
        lines of invoice N always exist before invoice N+1's row.

        Input: ``[{"invoice": dict, "lineItems": list[dict]}, ...]`` —
        the journal + row payload come from ``invoice``, the line
        payloads from ``lineItems`` (built by the router, WO[#27.8]
        Step 4).

        Sequence corrections retained from earlier WOs: journal-phase
        errors raise ``MaconomyInvoiceServiceError`` (router -> HTTP 500,
        batch prerequisite); row-phase errors are captured per invoice
        as FAILED entries (and its lines are NOT created) with the
        last-good concurrency token reused; line-phase failures are
        contained per invoice by ``_create_lines_for_invoice`` (never
        raises) — a line problem never fails the journal or other
        invoices (FR-9).

        Return contract (response EXTRACTION only — card/row/line
        payloads untouched):
        ``{"journal": <journal payload>,
           "journalnumber": str,                # "" if not in response
           "invoices": [{"invoice_id", "status",
                         "result"?|("message"),
                         "journallinenumber": int|None,  # SUCCESS only;
                                            # = the row's `linenumber`
                        }, ...],
           "lines": [{"invoice_id", "line_index",
                      "status": "SUCCESS"|"FAILED",
                      "result"?|"message"?}, ...],
           "line_error": str | None}``.
        """
        print("======= create_journal_with_invoices =========")

        try:
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)

                instance_id, concurrency_token = (
                    await self._retrieve_vendor_invoice_instance(
                        client=client,
                        reconnect_token=reconnect_token,
                    )
                )

                _, concurrency_token = await self._initialize_vendor_invoice_card(
                    client=client,
                    reconnect_token=reconnect_token,
                    instance_id=instance_id,
                    concurrency_token=concurrency_token,
                )

                # --- Create the journal (card pane, STATIC payload) ---
                print("======== Journal Creation Started =========")
                card_url = (
                    f"{self._vendor_invoice_url()}/instances/"
                    f"{instance_id}/data/panes/card"
                )
                card_headers = self._container_headers(reconnect_token)
                card_headers["Maconomy-Concurrency-Control"] = concurrency_token
                card_payload = map_concur_invoice_to_maconomy_vendor_invoice()
                card_response = await client.post(
                    card_url,
                    headers=card_headers,
                    json=card_payload,
                )
                card_response.raise_for_status()

                try:
                    journal_payload = card_response.json()
                except (KeyError, TypeError, ValueError) as json_exc:
                    raise MaconomyInvoiceServiceError(
                        "Invalid Maconomy journal response"
                    ) from json_exc

                if not isinstance(journal_payload, dict):
                    raise MaconomyInvoiceServiceError(
                        "Invalid Maconomy journal response"
                    )

                # Q-1 linkage extraction (WO[#27.8] Step 1) — PRIMARY
                # path per user 2026-11-10:
                # panes -> card -> records -> data -> journalnumber
                # ("" -> the line phase is skipped with line_error).
                journalnumber = self._extract_journal_number(journal_payload)

                # D-6: no journal number -> NO line can carry the
                # required journalnumber field; all line creation is
                # skipped for the whole run, rows unaffected.
                line_error: str | None = None
                if not journalnumber:
                    line_error = "journalnumber missing from journal response"
                    print(f"[invoice-api] {line_error} — lines will be skipped")

                concurrency_token = self._get_concurrency_token(card_response)
                print("========= Journal created ==========")

                # --- Initialize the invoice table pane ---
                _, concurrency_token = await self._initialize_vendor_invoice_table(
                    client=client,
                    reconnect_token=reconnect_token,
                    instance_id=instance_id,
                    concurrency_token=concurrency_token,
                )

                # --- Interleaved pass: row -> THAT invoice's lines
                # -> next row (FR-12 / WO[#27.8]) ---
                invoice_entries: list[dict[str, Any]] = []
                line_entries: list[dict[str, Any]] = []
                table_url = (
                    f"{self._vendor_invoice_url()}/instances/"
                    f"{instance_id}/data/panes/table"
                )

                for index, entry in enumerate(entries):
                    invoice = entry.get("invoice") or {}
                    if not isinstance(invoice, dict):
                        invoice = {}
                    line_items = entry.get("lineItems") or []
                    if not isinstance(line_items, list):
                        line_items = []
                    invoice_id = str(
                        invoice.get("PaymentRequestId")
                        or invoice.get("ID")
                        or ""
                    ).strip()

                    try:
                        row_payload = map_concur_invoice_to_maconomy_invoice_row(
                            invoice
                        )
                        row_headers = self._container_headers(reconnect_token)
                        row_headers["Maconomy-Concurrency-Control"] = (
                            concurrency_token
                        )
                        row_response = await client.post(
                            table_url,
                            headers=row_headers,
                            json=row_payload,
                        )
                        row_response.raise_for_status()

                        try:
                            row_result = row_response.json()
                        except (KeyError, TypeError, ValueError) as json_exc:
                            raise MaconomyInvoiceServiceError(
                                f"Invalid Maconomy invoice row response "
                                f"for invoice {index}"
                            ) from json_exc

                        if not isinstance(row_result, dict):
                            raise MaconomyInvoiceServiceError(
                                f"Invalid Maconomy invoice row response "
                                f"for invoice {index}"
                            )

                        # Q-1 linkage extraction (WO[#27.7] Step 1) —
                        # the row response's `linenumber` is the value
                        # the line phase embeds so each line lands on
                        # THIS invoice row.
                        journallinenumber = self._extract_row_line_number(
                            row_result
                        )
                        if journallinenumber is None:
                            # Diagnostic (user 2026-11-10 live miss):
                            # the load step needs this value — say so
                            # right where the row response was parsed
                            # (response-body dumps removed per
                            # WO[#27.10] — highlights only).
                            print(
                                f"[invoice-api] WARN: no extractable "
                                f"linenumber in row response "
                                f"(invoice_id={invoice_id}) — allocation "
                                f"lines of this invoice will FAIL"
                            )

                        invoice_entries.append(
                            {
                                "invoice_id": invoice_id,
                                "status": "SUCCESS",
                                "result": row_result,
                                "journallinenumber": journallinenumber,
                            }
                        )
                        concurrency_token = self._get_concurrency_token(
                            row_response
                        )
                        print(f"========= Invoice row {index} created =========")

                    except (
                        ValueError,
                        MaconomyInvoiceServiceError,
                        httpx.HTTPError,
                    ) as exc:
                        # One failed invoice row never terminates the batch;
                        # the last-good concurrency token is reused for the
                        # next row (documented assumption, WO[#21.9]).
                        print(
                            f"Invoice row {index} failed "
                            f"(invoice_id={invoice_id}): {exc}"
                        )
                        invoice_entries.append(
                            {
                                "invoice_id": invoice_id,
                                "status": "FAILED",
                                "message": str(exc),
                            }
                        )
                        continue

                    # --- INTERLEAVE: create THIS invoice's allocation
                    # lines immediately after its row (WO[#27.8]) ---
                    if not journalnumber or not line_items:
                        # D-6 (no journalnumber -> lines skipped) or
                        # D-2 (no line items -> nothing to create).
                        continue
                    print(
                        f"--- invoice {invoice_id}: row created, creating "
                        f"its {len(line_items)} allocation line(s) ---"
                    )
                    line_entries.extend(
                        await self._create_lines_for_invoice(
                            client=client,
                            reconnect_token=reconnect_token,
                            invoice_id=invoice_id,
                            journallinenumber=journallinenumber,
                            line_items=line_items,
                            journalnumber=journalnumber,
                            line_offset=len(line_entries),
                        )
                    )

                print(
                    "========= Journal + invoice rows + interleaved lines "
                    "completed =========="
                )
                return {
                    "journal": journal_payload,
                    "journalnumber": journalnumber,
                    "invoices": invoice_entries,
                    "lines": line_entries,
                    "line_error": line_error,
                }

        except MaconomyInvoiceServiceError:
            raise
        except httpx.HTTPError as http_exc:
            raise MaconomyInvoiceServiceError(
                "Maconomy request failed"
            ) from http_exc

    # ------------------------------------------------------------------
    # vendorinvoiceallocation lines (Req[#27] FR-5..FR-9, WO[#27.2])
    # ------------------------------------------------------------------
    async def _retrieve_vendor_invoice_allocation_instance(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> tuple[str, str]:
        """POST /instances -> (instance key, concurrency token) (FR-5a)."""
        url = f"{self._vendor_invoice_allocation_url()}/instances"
        payload = build_vendor_invoice_allocation_instance_payload()

        print("======= _retrieve_vendor_invoice_allocation_instance ==========")
        response = await client.post(
            url,
            headers=self._container_headers(reconnect_token),
            json=payload,
        )
        response.raise_for_status()

        try:
            instance_id = response.json()["meta"]["containerInstanceId"]
            instance_id = str(uuid.UUID(instance_id))
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy invoice allocation instance response"
            ) from exc

        concurrency_token = self._get_concurrency_token(response)
        return instance_id, concurrency_token

    async def _load_vendor_invoice_allocation_data(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        journalnumber: str,
        journallinenumber: int | None,
    ) -> str:
        """Load the parent invoice row into a fresh allocation instance.

        **Manual Maconomy procedure (user 2026-11-10):** (1) retrieve
        instance -> (2) **get the data using linenumber + journalnumber**
        -> (3) init the table -> (4) POST line rows. Without step (2)
        the instance holds only the field slice (no record) and
        ``table/init`` fails with HTTP 400 ``"Your request cannot be
        fulfilled when no data has been loaded."``

        URL — exact manual form, **``linenumber`` FIRST**:
        ``.../instances/{id}/data;linenumber={journallinenumber};journalnumber={journalnumber}``
        (Maconomy's own link template ``.../data;linenumber={1};journalnumber={0}``),
        body ``{}``. Returns the new concurrency token. Missing
        linkage values or a failed HTTP call raise
        ``MaconomyInvoiceServiceError`` (the caller's D-4 handler then
        records FAILED entries for THIS invoice only).
        """
        journalnumber = str(journalnumber or "").strip()
        if not journalnumber or journallinenumber is None:
            raise MaconomyInvoiceServiceError(
                "Cannot load allocation data: journalnumber/linenumber "
                f"missing (journalnumber={journalnumber!r}, "
                f"journallinenumber={journallinenumber!r})"
            )

        url = (
            f"{self._vendor_invoice_allocation_url()}/instances/"
            f"{instance_id}/data;linenumber={journallinenumber}"
            f";journalnumber={quote(journalnumber, safe='')}"
        )
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token

        print("========= _load_vendor_invoice_allocation_data =========")
        response = await client.post(url, headers=headers, json={})
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyInvoiceServiceError(
                "Failed to load allocation data for journal "
                f"{journalnumber} (linenumber={journallinenumber}, "
                f"instance {instance_id}): {exc}"
            ) from exc

        return self._get_concurrency_token(response)

    async def _initialize_vendor_invoice_allocation_table(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
    ) -> tuple[dict[str, Any], str]:
        """POST /data/panes/table/init ({"row":"end"}) -> (data, token) (FR-5c)."""
        url = (
            f"{self._vendor_invoice_allocation_url()}/instances/"
            f"{instance_id}/data/panes/table/init"
        )
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token
        payload = build_vendor_invoice_table_init_payload()

        print("========= _initialize_vendor_invoice_allocation_table =========")
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()

        try:
            initialized_data = response.json()["data"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy invoice allocation table initialization "
                "response"
            ) from exc

        if not isinstance(initialized_data, dict):
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy invoice allocation table initialization "
                "response"
            )

        new_concurrency_token = self._get_concurrency_token(response)
        print("Vendor invoice allocation table initialized!")
        return dict(initialized_data), new_concurrency_token

    async def _create_vendor_invoice_allocation_row(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        row_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """POST ONE allocation line row -> (result, new token) (FR-6).

        The Invoice Line API:
        POST .../vendorinvoiceallocation/instances/{id}/data/panes/table
        """
        url = (
            f"{self._vendor_invoice_allocation_url()}/instances/"
            f"{instance_id}/data/panes/table"
        )
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token

        print("======= _create_vendor_invoice_allocation_row =========")
        # Debug: invoice API visibility — POST payload + status/body
        print(f"[invoice-api] POST {url} payload={row_payload}")
        response = await client.post(url, headers=headers, json=row_payload)
        print(
            f"[invoice-api] POST {url} -> "
            f"status={response.status_code} body={response.text}"
        )
        response.raise_for_status()

        try:
            row_result = response.json()
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy invoice allocation row response"
            ) from exc

        if not isinstance(row_result, dict):
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy invoice allocation row response"
            )

        new_concurrency_token = self._get_concurrency_token(response)
        return row_result, new_concurrency_token

    async def _create_lines_for_invoice(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        invoice_id: str,
        journallinenumber: int | None,
        line_items: list[dict[str, Any]],
        journalnumber: str,
        line_offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Create ALL allocation lines of ONE invoice on its OWN instance.

        Extracted verbatim from ``create_invoice_lines`` (WO[#27.8]
        Step 2) so the journal flow can invoke it **immediately after
        the invoice row is created** (interleaved flow, user
        2026-11-10): row -> THIS invoice's lines -> next row.

        Behavior (WO[#27.7] + corrections 2026-11-10):
        - zero ``line_items`` -> ``[]`` (no instance retrieved, D-2);
        - **manual Maconomy procedure (user 2026-11-10):** ONE new
          ``vendorinvoiceallocation`` instance key -> **load the parent
          invoice row** ``data;linenumber={jln};journalnumber={jn}``
          -> **table init ``{"row": "end"}`` ONLY** (there is NO card
          init on this container's line-creation path) -> line POSTs;
          the load is what makes table init legal (400 "no data has
          been loaded" without it), shared by all of THIS invoice's
          lines (A-4 superseded; distinct from the phase-3
          ``vendorinvoices`` instance); lifecycle failure -> one FAILED
          entry per line and return (D-4) — **never raises**;
        - then each line: ``map_concur_invoice_line_to_allocation_row(
          ..., journalnumber, journallinenumber)`` + sequential POST,
          token chained **within this invoice only** (the caller's
          ``vendorinvoices`` chain is untouched — different containers
          have separate concurrency control), per-line fault tolerance
          (expense pattern, FR-8).
        ``line_offset`` only offsets the progress-print counter.
        """
        lines: list[dict[str, Any]] = []
        if not line_items:
            # D-2: nothing to create -> no instance retrieved.
            return lines

        # --- Per-invoice lifecycle: NEW instance key used for ALL
        # lines of THIS invoice (A-4 superseded). ---
        try:
            print(
                f"========= Allocation instance lifecycle "
                f"started (invoice_id={invoice_id}) ========="
            )
            instance_id, concurrency_token = (
                await self._retrieve_vendor_invoice_allocation_instance(
                    client=client,
                    reconnect_token=reconnect_token,
                )
            )
            # --- Manual procedure step 2 (user 2026-11-10): load the
            # parent invoice row by linenumber + journalnumber BEFORE
            # table init — without it init fails with 400 "no data has
            # been loaded". ---
            concurrency_token = (
                await self._load_vendor_invoice_allocation_data(
                    client=client,
                    reconnect_token=reconnect_token,
                    instance_id=instance_id,
                    concurrency_token=concurrency_token,
                    journalnumber=journalnumber,
                    journallinenumber=journallinenumber,
                )
            )
            # --- Manual procedure step 3 (user 2026-11-10): the ONLY
            # init on this container's line path — table init
            # {"row": "end"}; there is NO card init. ---
            _, concurrency_token = (
                await self._initialize_vendor_invoice_allocation_table(
                    client=client,
                    reconnect_token=reconnect_token,
                    instance_id=instance_id,
                    concurrency_token=concurrency_token,
                )
            )
            print(
                f"[invoice-api] invoice {invoice_id} -> "
                f"allocation instance {instance_id}"
            )
            print("========= Allocation instance ready =========")
        except (MaconomyInvoiceServiceError, httpx.HTTPError) as exc:
            # D-4: THIS invoice's instance failed -> its lines are
            # FAILED; the remaining invoices still run.
            print(
                f"Allocation instance failed "
                f"(invoice_id={invoice_id}): {exc}"
            )
            for failed_line_index in range(len(line_items)):
                lines.append(
                    {
                        "invoice_id": invoice_id,
                        "line_index": failed_line_index,
                        "status": "FAILED",
                        "message": str(exc),
                    }
                )
            return lines

        # --- This invoice's lines: sequential, one POST at a time
        # (FR-8), all against the instance above. ---
        attempted = 0
        for line_index, line_item in enumerate(line_items):
            try:
                row_payload = map_concur_invoice_line_to_allocation_row(
                    line_item,
                    journalnumber=journalnumber,
                    journallinenumber=journallinenumber,
                )
                result, concurrency_token = (
                    await self._create_vendor_invoice_allocation_row(
                        client=client,
                        reconnect_token=reconnect_token,
                        instance_id=instance_id,
                        concurrency_token=concurrency_token,
                        row_payload=row_payload,
                    )
                )
                lines.append(
                    {
                        "invoice_id": invoice_id,
                        "line_index": line_index,
                        "status": "SUCCESS",
                        "result": result,
                    }
                )
                print(
                    f"========= Invoice line {line_offset + attempted} "
                    f"created ========="
                )
            except (
                ValueError,
                MaconomyInvoiceServiceError,
                httpx.HTTPError,
            ) as exc:
                # One failed line never terminates the batch; the
                # last-good concurrency token is reused for the next
                # line (expense pattern, FR-8).
                print(
                    f"Invoice line failed "
                    f"(invoice_id={invoice_id}, "
                    f"line_index={line_index}): {exc}"
                )
                lines.append(
                    {
                        "invoice_id": invoice_id,
                        "line_index": line_index,
                        "status": "FAILED",
                        "message": str(exc),
                    }
                )
            attempted += 1

        return lines

    async def create_invoice_lines(
        self,
        line_batches: list[dict[str, Any]],
        journalnumber: str,
    ) -> dict[str, Any]:
        """Create Maconomy allocation lines for the created invoices (FR-5..FR-9).

        Input:  ``[{"invoice_id": str, "journallinenumber": int|None,
                "lineItems": list[dict]}, ...]``
                (only SUCCESS invoices — built by the router);
                ``journalnumber`` (str) is passed separately because it
                is the same for every batch in a run (the phase-3
                journal). Both values are the Q-1 linkage fields the
                mapper embeds in every line payload — the batch's
                ``journallinenumber`` is the invoice row's
                ``linenumber`` (WO[#27.6]/WO[#27.7]).
        Output: ``{"lines": [{"invoice_id", "line_index",
                "status": "SUCCESS"|"FAILED", "result"?|"message"?}, ...],
                "error": str | None}``.

        **THIN WRAPPER (WO[#27.8] D-5, decision: KEEP)** — retained for
        backwards compatibility / off-line batch runs; the live router no
        longer calls it (the interleaved journal flow invokes
        ``_create_lines_for_invoice`` directly per invoice). The
        per-invoice behavior — one NEW ``vendorinvoiceallocation``
        instance key per invoice, sequential line POSTs with token
        chaining, per-line fault tolerance, zero-line skip — now lives
        in ``_create_lines_for_invoice`` (A-4 superseded).
        """
        print("======= create_invoice_lines =========")

        lines: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)

                line_counter = 0
                for batch in line_batches:
                    invoice_id = str(batch.get("invoice_id") or "").strip()
                    batch_lines = batch.get("lineItems") or []
                    if not batch_lines:
                        # D-2: nothing to create -> no instance retrieved.
                        continue

                    entries = await self._create_lines_for_invoice(
                        client=client,
                        reconnect_token=reconnect_token,
                        invoice_id=invoice_id,
                        journallinenumber=batch.get("journallinenumber"),
                        line_items=batch_lines,
                        journalnumber=journalnumber,
                        line_offset=line_counter,
                    )
                    lines.extend(entries)
                    line_counter += len(batch_lines)

                print("========= Invoice lines completed ==========")
                return {"lines": lines, "error": None}

        except (MaconomyInvoiceServiceError, httpx.HTTPError) as exc:
            # Never raises (FR-9): global lifecycle/auth failure ->
            # error dict.
            print(f"Invoice line phase failed: {exc}")
            return {"lines": lines, "error": str(exc)}
