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
    build_vendor_invoice_instance_payload,
    build_vendor_invoice_table_init_payload,
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

    async def _retrieve_vendor_invoice_instance(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> tuple[str, str]:
        url = f"{self._vendor_invoice_url()}/instances"
        payload = build_vendor_invoice_instance_payload()

        print("======= _retrieve_vendor_invoice_instance ==========")
        # Debug: invoice API visibility — POST payload + status/body
        print(f"[invoice-api] POST {url} payload={payload}")
        response = await client.post(
            url,
            headers=self._container_headers(reconnect_token),
            json=payload,
        )
        print(
            f"[invoice-api] POST {url} -> "
            f"status={response.status_code} body={response.text}"
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
        # Debug: invoice API visibility — POST payload + status/body
        print(f"[invoice-api] POST {url} payload={{}}")
        response = await client.post(
            url,
            headers=headers,
            json={},
        )
        print(
            f"[invoice-api] POST {url} -> "
            f"status={response.status_code} body={response.text}"
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
        # Debug: invoice API visibility — POST payload + status/body
        print(f"[invoice-api] POST {url} payload={payload}")
        response = await client.post(
            url,
            headers=headers,
            json=payload,
        )
        print(
            f"[invoice-api] POST {url} -> "
            f"status={response.status_code} body={response.text}"
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

    async def create_journal_with_invoices(
        self,
        invoices: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create ONE journal (static card) + all invoices as table rows.

        Sequence (FR-12 corrected, WO[#21.9]):
        retrieve instance -> init card -> create card (STATIC journal
        payload) -> init table -> for each Concur invoice: dynamic row
        map (CurrencyCode/InvoiceNumber/InvoiceDate) + POST table.
        Journal-phase errors raise ``MaconomyInvoiceServiceError`` (the
        router maps them to HTTP 500 — batch prerequisite); row-phase
        errors are captured per invoice as FAILED entries and the batch
        continues with the last-good concurrency token.
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
                # Debug: invoice API visibility — POST payload + status/body
                print(f"[invoice-api] POST {card_url} payload={card_payload}")
                card_response = await client.post(
                    card_url,
                    headers=card_headers,
                    json=card_payload,
                )
                print(
                    f"[invoice-api] POST {card_url} -> "
                    f"status={card_response.status_code} "
                    f"body={card_response.text}"
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

                concurrency_token = self._get_concurrency_token(card_response)
                print("========= Journal created ==========")

                # --- Initialize the invoice table pane ---
                _, concurrency_token = await self._initialize_vendor_invoice_table(
                    client=client,
                    reconnect_token=reconnect_token,
                    instance_id=instance_id,
                    concurrency_token=concurrency_token,
                )

                # --- Invoice rows: one per Concur invoice (FR-12) ---
                invoice_entries: list[dict[str, Any]] = []
                table_url = (
                    f"{self._vendor_invoice_url()}/instances/"
                    f"{instance_id}/data/panes/table"
                )

                for index, invoice in enumerate(invoices):
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
                        # Debug: invoice API — payload + status/body
                        print(
                            f"[invoice-api] POST {table_url} "
                            f"payload={row_payload}"
                        )
                        row_response = await client.post(
                            table_url,
                            headers=row_headers,
                            json=row_payload,
                        )
                        print(
                            f"[invoice-api] POST {table_url} -> "
                            f"status={row_response.status_code} "
                            f"body={row_response.text}"
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

                        invoice_entries.append(
                            {
                                "invoice_id": invoice_id,
                                "status": "SUCCESS",
                                "result": row_result,
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

                print("========= Journal + invoice rows completed ==========")
                return {
                    "journal": journal_payload,
                    "invoices": invoice_entries,
                }

        except MaconomyInvoiceServiceError:
            raise
        except httpx.HTTPError as http_exc:
            raise MaconomyInvoiceServiceError(
                "Maconomy request failed"
            ) from http_exc
