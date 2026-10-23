"""Service for creating employee vendors in the Maconomy vendorcard container."""

import base64
import uuid
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

# Fields requested from the vendorcard instance (Req FR-2).
VENDOR_CARD_FIELDS = (
    "controlaccountcode",
    "currency",
    "deliverymode",
    "deliveryterms",
    "departmentnumber",
    "employeenamevar",
    "employeenumber",
    "inventorynumber",
    "language",
    "linkingrulename",
    "name1",
    "name1var",
    "parentvendor",
    "parentvendorname1",
    "paymentmode",
    "paymentterms",
    "paymentvendor",
    "responsible",
    "responsiblenamevar",
    "subordinaterelationnamevar",
    "timeregistrationunit",
    "vendorgroup",
    "vendornumber",
)


class MaconomyVendorServiceError(Exception):
    """Raised when a Maconomy vendor operation fails."""


class MaconomyVendorService:
    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    async def create_employee_vendor(
        self,
        *,
        employee_number: str,
        employee_name: str,
    ) -> dict[str, Any]:
        """Create one employee vendor (E-{employeenumber}) in vendorcard."""

        normalized_employee_number = (
            str(employee_number).strip()
        )

        if not normalized_employee_number:
            raise MaconomyVendorServiceError(
                "Employee number is required"
            )

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                reconnect_token = (
                    await self._get_reconnect_token(
                        client
                    )
                )

                instance_id, concurrency_token = (
                    await self._start_vendor_instance(
                        client,
                        reconnect_token,
                    )
                )

                initialized_data, concurrency_token = (
                    await self._initialize_vendor_card(
                        client,
                        reconnect_token,
                        instance_id,
                        concurrency_token,
                    )
                )

                vendor_data = {
                    **initialized_data,
                    **self._build_vendor_payload(
                        normalized_employee_number,
                        employee_name,
                    ),
                }

                return await self._submit_vendor_card(
                    client,
                    reconnect_token,
                    instance_id,
                    concurrency_token,
                    vendor_data,
                )



        except httpx.RequestError as exc:
            request = getattr(
                exc,
                "request",
                None,
            )

            request_url = (
                str(request.url)
                if request is not None
                else self.settings.maconomy_url
            )

            raise MaconomyVendorServiceError(
                "Unable to connect to Maconomy: "
                f"{type(exc).__name__} while calling "
                f"{request_url}: {exc}"
            ) from exc

    @staticmethod
    def _build_vendor_payload(
        employee_number: str,
        employee_name: str,
    ) -> dict[str, str]:
        """Build the vendor card fields per Req FR-3/FR-4/FR-6."""

        return {
            "vendornumber": f"E-{employee_number}",
            "name1": employee_name,
            "paymentvendor": "",
            "controlaccountcode": "nil",
            "departmentnumber": "nil",
            "vendorgroup": "nil",
            "deliverymode": "nil",
            "deliveryterms": "nil",
            "paymentmode": "",
            "paymentterms": "nil",
            "currency": "nil",
            "language": "nil",
            "inventorynumber": "nil",
            "responsible": employee_number,
            "linkingrulename": "Standard",
            "parentvendor": "TemplateVendor",
            "employeenumber": employee_number,
            "timeregistrationunit": "hours",
        }

    def _vendorcard_url(self) -> str:
        shortname = quote(
            self.settings.maconomy_shortname,
            safe="",
        )

        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/"
            f"{shortname}/vendorcard"
        )

    async def _start_vendor_instance(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> tuple[str, str]:
        url = f"{self._vendorcard_url()}/instances"

        payload = {
            "panes": {
                "card": {
                    "fields": list(VENDOR_CARD_FIELDS),
                }
            }
        }

        response = await client.post(
            url,
            headers=self._container_headers(
                reconnect_token
            ),
            json=payload,
        )
        response.raise_for_status()

        try:
            instance_id = response.json()["meta"][
                "containerInstanceId"
            ]
            instance_id = str(
                uuid.UUID(instance_id)
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise MaconomyVendorServiceError(
                "Invalid Maconomy vendor instance response"
            ) from exc

        concurrency_token = (
            self._get_concurrency_token(response)
        )

        return instance_id, concurrency_token

    async def _initialize_vendor_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
    ) -> tuple[dict[str, Any], str]:
        url = (
            f"{self._vendorcard_url()}/instances/"
            f"{instance_id}/data/panes/card/init"
        )

        headers = self._container_headers(
            reconnect_token
        )
        headers["Maconomy-Concurrency-Control"] = (
            concurrency_token
        )

        response = await client.post(
            url,
            headers=headers,
            json={},
        )
        response.raise_for_status()

        try:
            initialized_data = response.json()["data"]

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise MaconomyVendorServiceError(
                "Invalid Maconomy vendor "
                "initialization response"
            ) from exc

        if not isinstance(initialized_data, dict):
            raise MaconomyVendorServiceError(
                "Invalid Maconomy vendor "
                "initialization response"
            )

        new_concurrency_token = (
            self._get_concurrency_token(response)
        )

        return (
            dict(initialized_data),
            new_concurrency_token,
        )

    async def _submit_vendor_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        vendor_data: dict[str, Any],
    ) -> dict[str, Any]:
        url = (
            f"{self._vendorcard_url()}/instances/"
            f"{instance_id}/data/panes/card"
        )

        headers = self._container_headers(
            reconnect_token
        )
        headers["Maconomy-Concurrency-Control"] = (
            concurrency_token
        )

        response = await client.post(
            url,
            headers=headers,
            json={"data": vendor_data},
        )

        if response.is_error:
            response_text = (
                response.text.strip()
                or "<empty Maconomy response body>"
            )

            raise MaconomyVendorServiceError(
                "Maconomy rejected the vendor card "
                f"with HTTP {response.status_code}: "
                f"{response_text[:2000]}"
            )

        try:
            card = response.json()["panes"]["card"]
            records = card["records"]

            if (
                card["meta"]["rowCount"] != 1
                or len(records) != 1
            ):
                raise MaconomyVendorServiceError(
                    "Unexpected Maconomy vendor record count"
                )

            created_vendor = records[0]["data"]

        except MaconomyVendorServiceError:
            raise

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise MaconomyVendorServiceError(
                "Invalid Maconomy vendor creation response"
            ) from exc

        if not isinstance(created_vendor, dict):
            raise MaconomyVendorServiceError(
                "Invalid Maconomy vendor creation response"
            )

        vendor_number = created_vendor.get(
            "vendornumber"
        )

        if (
            not isinstance(vendor_number, str)
            or not vendor_number.strip()
        ):
            raise MaconomyVendorServiceError(
                "Maconomy did not return a vendor number"
            )

        return created_vendor

    async def _get_reconnect_token(
        self,
        client: httpx.AsyncClient,
    ) -> str:
        shortname = quote(
            self.settings.maconomy_shortname,
            safe="",
        )

        url = (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/auth/{shortname}/login"
        )

        credentials = (
            f"{self.settings.maconomy_username}:"
            f"{self.settings.maconomy_password.get_secret_value()}"
        )

        encoded_credentials = base64.b64encode(
            credentials.encode("utf-8")
        ).decode("ascii")

        response = await client.get(
            url,
            headers={
                "Accept": AUTH_CONTENT_TYPE,
                "Maconomy-Authentication": "X-Reconnect",
                "Authorization": (
                    f"Basic {encoded_credentials}"
                ),
            },
        )
        response.raise_for_status()

        reconnect_token = response.headers.get(
            "Maconomy-Reconnect",
            "",
        ).strip()

        if (
            response.status_code != 204
            or not reconnect_token
        ):
            raise MaconomyVendorServiceError(
                "Maconomy authentication failed"
            )

        return reconnect_token

    @staticmethod
    def _get_concurrency_token(
        response: httpx.Response,
    ) -> str:
        concurrency_token = response.headers.get(
            "Maconomy-Concurrency-Control",
            "",
        ).strip()

        try:
            return str(
                uuid.UUID(concurrency_token)
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise MaconomyVendorServiceError(
                "Invalid Maconomy concurrency token"
            ) from exc

    @staticmethod
    def _container_headers(
        reconnect_token: str,
    ) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": (
                f"X-Reconnect {reconnect_token}"
            ),
        }
