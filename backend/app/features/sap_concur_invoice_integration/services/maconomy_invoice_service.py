"""Maconomy vendor-invoice creation (Phase 2 of Req[#21]).

Orchestrates the user-specified creation sequence on ONE container
instance: retrieve instance -> init card -> create card -> init table
-> create line rows (for-loop). Maconomy auth, container headers, and
the concurrency-token chain are copied as-is from
`sap_concur_integration/services/maconomy_services.py` (Reconnect-token
Basic auth) per requirement FR-2/FR-9.
"""

import base64
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.features.sap_concur_invoice_integration.mappers import (
    build_static_line_item_payloads,
    build_vendor_invoice_instance_payload,
    build_vendor_invoice_table_init_payload,
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
        # Debug: line-related API visibility (status + raw body)
        print(
            f"[line-api] POST {url} -> "
            f"status={response.status_code} body={response.text}"
        )

        response.raise_for_status()

        try:
            initialized_data = response.json()["data"]

        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy vendor invoice line initialization response"
            ) from exc

        if not isinstance(initialized_data, dict):
            raise MaconomyInvoiceServiceError(
                "Invalid Maconomy vendor invoice line initialization response"
            )

        new_concurrency_token = self._get_concurrency_token(response)
        print("Vendor invoice table initialized!")
        return dict(initialized_data), new_concurrency_token

    async def create_vendor_invoice(self) -> dict[str, Any]:
        """Create a vendor invoice + line rows in Maconomy.

        Sequence on ONE instance (FR-10):
        retrieve instance -> init card -> create card -> init table
        -> for-loop line-row creates; concurrency token chained per step.
        Payloads come from the static mappers (FR-8).
        """
        print("=========== create_vendor_invoice =============")
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

                # --- Create the invoice (card pane) ---
                print("======== Vendor Invoice Creation Started ========")
                card_url = (
                    f"{self._vendor_invoice_url()}/instances/"
                    f"{instance_id}/data/panes/card"
                )
                card_headers = self._container_headers(reconnect_token)
                card_headers["Maconomy-Concurrency-Control"] = concurrency_token
                card_response = await client.post(
                    card_url,
                    headers=card_headers,
                    json=map_concur_invoice_to_maconomy_vendor_invoice(),
                )
                card_response.raise_for_status()

                try:
                    invoice_payload = card_response.json()
                except (KeyError, TypeError, ValueError) as json_exc:
                    raise MaconomyInvoiceServiceError(
                        "Invalid Maconomy vendor invoice response"
                    ) from json_exc

                if not isinstance(invoice_payload, dict):
                    raise MaconomyInvoiceServiceError(
                        "Invalid Maconomy vendor invoice response"
                    )

                concurrency_token = self._get_concurrency_token(card_response)
                print("========= Vendor invoice card created ==========")

                # --- Initialize the line table pane ---
                _, concurrency_token = await self._initialize_vendor_invoice_table(
                    client=client,
                    reconnect_token=reconnect_token,
                    instance_id=instance_id,
                    concurrency_token=concurrency_token,
                )

                # --- Create the line rows (for-loop over line items) ---
                line_payloads: list[dict[str, Any]] = []
                line_items = build_static_line_item_payloads(count=1)

                table_url = (
                    f"{self._vendor_invoice_url()}/instances/"
                    f"{instance_id}/data/panes/table"
                )

                for index, line_data in enumerate(line_items):
                    print(f"---- Creating vendor invoice line {index} ----")
                    line_headers = self._container_headers(reconnect_token)
                    line_headers["Maconomy-Concurrency-Control"] = (
                        concurrency_token
                    )
                    line_response = await client.post(
                        table_url,
                        headers=line_headers,
                        json=line_data,
                    )
                    # Debug: line-related API visibility (status + body)
                    print(
                        f"[line-api] POST {table_url} -> "
                        f"status={line_response.status_code} "
                        f"body={line_response.text}"
                    )
                    line_response.raise_for_status()

                    try:
                        line_payload = line_response.json()
                    except (KeyError, TypeError, ValueError) as json_exc:
                        raise MaconomyInvoiceServiceError(
                            f"Invalid Maconomy vendor invoice line response "
                            f"for line {index}"
                        ) from json_exc

                    if not isinstance(line_payload, dict):
                        raise MaconomyInvoiceServiceError(
                            f"Invalid Maconomy vendor invoice line response "
                            f"for line {index}"
                        )

                    line_payloads.append(line_payload)
                    concurrency_token = self._get_concurrency_token(line_response)
                    print(f"========= Line {index} created =========")

                print("========= Vendor invoice creation completed ==========")
                return {
                    "invoice": invoice_payload,
                    "lines": line_payloads,
                }

        except MaconomyInvoiceServiceError:
            raise
        except httpx.HTTPError as http_exc:
            raise MaconomyInvoiceServiceError(
                "Maconomy request failed"
            ) from http_exc
