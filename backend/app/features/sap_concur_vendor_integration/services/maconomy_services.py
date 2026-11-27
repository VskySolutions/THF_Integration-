import base64
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.features.sap_concur_vendor_integration.mappers.maconomy_vendor_mapper import (
    build_vendorcard_instance_payload,
    map_concur_vendor_to_maconomy_vendor_card,
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


class MaconomyServiceError(Exception):
    pass


class MaconomyService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self._reconnect_token: str | None = None
        self._country_names: dict[str, str] | None = None

    async def authenticate(self) -> None:
        if self._reconnect_token is not None:
            return

        credentials = (
            f"{self.settings.maconomy_username}:"
            f"{self.settings.maconomy_password.get_secret_value()}"
        )
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        shortname = quote(self.settings.maconomy_shortname, safe="")
        try:
            response = await self.client.get(
                f"{self.settings.maconomy_url}/maconomy-api/auth/{shortname}/login",
                headers={
                    "Accept": AUTH_CONTENT_TYPE,
                    "Maconomy-Authentication": "X-Reconnect",
                    "Authorization": f"Basic {encoded}",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyServiceError(
                "Maconomy authentication request failed"
            ) from exc

        token = response.headers.get("Maconomy-Reconnect", "").strip()
        if response.status_code != 204 or not token:
            raise MaconomyServiceError("Invalid Maconomy authentication response")
        self._reconnect_token = token

    def _container_headers(self) -> dict[str, str]:
        if self._reconnect_token is None:
            raise MaconomyServiceError("Maconomy has not been authenticated")
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {self._reconnect_token}",
        }

    def _vendorcard_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/{shortname}/vendorcard"
        )

    def _countries_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/{shortname}/countries"
        )

    @staticmethod
    def _get_concurrency_token(response: httpx.Response) -> str:
        concurrency_token = response.headers.get(
            "Maconomy-Concurrency-Control", ""
        ).strip()
        try:
            return str(uuid.UUID(concurrency_token))
        except (TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy concurrency token"
            ) from exc

    async def _retrieve_vendor_instance(self) -> tuple[str, str]:
        url = f"{self._vendorcard_url()}/instances"
        payload = build_vendorcard_instance_payload()
        response = await self.client.post(
            url,
            headers=self._container_headers(),
            json=payload,
        )
        response.raise_for_status()
        try:
            instance_id = response.json()["meta"]["containerInstanceId"]
            instance_id = str(uuid.UUID(instance_id))
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy vendor instance response"
            ) from exc
        concurrency_token = self._get_concurrency_token(response)
        return instance_id, concurrency_token

    async def _initialize_vendor_card(
        self,
        instance_id: str,
        concurrency_token: str,
    ) -> tuple[dict[str, Any], str]:
        url = (
            f"{self._vendorcard_url()}/instances/"
            f"{instance_id}/data/panes/card/init"
        )
        headers = self._container_headers()
        headers["Maconomy-Concurrency-Control"] = concurrency_token
        response = await self.client.post(url, headers=headers, json={})
        response.raise_for_status()
        try:
            initialized_data = response.json()["data"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy vendor initialization response"
            ) from exc
        if not isinstance(initialized_data, dict):
            raise MaconomyServiceError(
                "Invalid Maconomy vendor initialization response"
            )
        new_concurrency_token = self._get_concurrency_token(response)
        return dict(initialized_data), new_concurrency_token

    async def _submit_vendor_card(
        self,
        instance_id: str,
        concurrency_token: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        url = (
            f"{self._vendorcard_url()}/instances/"
            f"{instance_id}/data/panes/card"
        )
        headers = self._container_headers()
        headers["Maconomy-Concurrency-Control"] = concurrency_token
        response = await self.client.post(url, headers=headers, json=payload)
        if response.is_error:
            response_text = (
                response.text.strip() or "<empty Maconomy response body>"
            )
            raise MaconomyServiceError(
                "Maconomy rejected the vendor card "
                f"with HTTP {response.status_code}: "
                f"{response_text[:2000]}"
            )
        try:
            card = response.json()["panes"]["card"]
            records = card["records"]
            if card["meta"]["rowCount"] != 1 or len(records) != 1:
                raise MaconomyServiceError(
                    "Unexpected Maconomy vendor record count"
                )
            created_vendor = records[0]["data"]
        except MaconomyServiceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy vendor creation response"
            ) from exc
        if not isinstance(created_vendor, dict):
            raise MaconomyServiceError(
                "Invalid Maconomy vendor creation response"
            )
        vendor_number = created_vendor.get("vendornumber")
        if not isinstance(vendor_number, str) or not vendor_number.strip():
            raise MaconomyServiceError(
                "Maconomy did not return a vendor number"
            )
        return created_vendor

    async def create_vendor(
        self, sap_vendor: dict[str, Any]
    ) -> dict[str, Any]:
        await self.authenticate()
        country_names = await self.get_country_names()

        try:
            payload = map_concur_vendor_to_maconomy_vendor_card(
                sap_vendor,
                country_names,
            )
        except ValueError as exc:
            raise MaconomyServiceError(str(exc)) from exc

        try:
            instance_id, concurrency_token = (
                await self._retrieve_vendor_instance()
            )

            initialized_data, concurrency_token = (
                await self._initialize_vendor_card(
                    instance_id, concurrency_token
                )
            )
            payload["data"] = {**initialized_data, **payload["data"]}
            return await self._submit_vendor_card(
                instance_id, concurrency_token, payload
            )
        except httpx.HTTPError as exc:
            raise MaconomyServiceError(
                "Maconomy vendor creation request failed"
            ) from exc

    async def get_all_vendors(self) -> list[dict[str, Any]]:
        await self.authenticate()
        url = f"{self._vendorcard_url()}/filter"
        limit = 1000
        offset = 0
        vendors: list[dict[str, Any]] = []
        pages = 0

        while True:
            if pages >= 100:
                raise MaconomyServiceError(
                    "Maconomy vendor retrieval exceeded the maximum "
                    "page ceiling of 100"
                )
            payload = {
                "fields": ["name1", "vendornumber"],
                "limit": limit,
                "offset": offset,
            }
            try:
                response = await self.client.post(
                    url,
                    headers=self._container_headers(),
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise MaconomyServiceError(
                    "Maconomy vendor request failed"
                ) from exc
            pages += 1

            try:
                pane = response.json()["panes"]["filter"]
                meta = pane["meta"]
                records = pane["records"]
            except (KeyError, TypeError, ValueError) as exc:
                raise MaconomyServiceError(
                    "Invalid Maconomy vendor filter response"
                ) from exc
            if (
                not isinstance(meta, dict)
                or not isinstance(records, list)
                or not all(isinstance(record, dict) for record in records)
            ):
                raise MaconomyServiceError(
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
                raise MaconomyServiceError(
                    "Invalid Maconomy vendor filter response"
                )

            for record in records:
                data = record.get("data")
                if not isinstance(data, dict):
                    raise MaconomyServiceError(
                        "Invalid Maconomy vendor filter response"
                    )
                vendors.append(
                    {
                        "vendornumber": str(
                            data.get("vendornumber") or ""
                        ).strip(),
                        "name1": str(data.get("name1") or "").strip(),
                    }
                )

            if len(records) < limit:
                break
            offset += limit

        return vendors

    async def get_country_names(self) -> dict[str, str]:
        if self._country_names is not None:
            return self._country_names

        await self.authenticate()
        url = f"{self._countries_url()}/filter"
        payload = {
            "fields": [
                "countrycode",
                "countrynumber",
                "eucountrycode",
                "isocode",
                "name",
            ],
            "limit": 500,
        }
        try:
            response = await self.client.post(
                url,
                headers=self._container_headers(),
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyServiceError(
                "Maconomy country list request failed"
            ) from exc

        try:
            pane = response.json()["panes"]["filter"]
            records = pane["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy countries filter response"
            ) from exc
        if not isinstance(records, list) or not all(
            isinstance(record, dict) for record in records
        ):
            raise MaconomyServiceError(
                "Invalid Maconomy countries filter response"
            )

        country_names: dict[str, str] = {}
        for record in records:
            data = record.get("data")
            if not isinstance(data, dict):
                raise MaconomyServiceError(
                    "Invalid Maconomy countries filter response"
                )
            name = str(data.get("name") or "").strip()
            if name:
                country_names.setdefault(name.casefold(), name)

        if not country_names:
            raise MaconomyServiceError(
                "Maconomy countries filter returned no usable values"
            )

        self._country_names = country_names
        return country_names

    async def get_vendor_by_code(
        self, vendor_code: str
    ) -> dict[str, Any] | None:
        """Look up ONE vendor in Maconomy by vendornumber.

        Single ``vendorcard/filter`` POST with a ``restriction``
        predicate (SQL-like ``field='value'`` syntax — same convention
        as ``showvendorinvoices``/``jobs``/``customercard`` filters
        elsewhere in this codebase). Returns the stripped
        ``{"vendornumber", "name1"}`` dict, or None when Maconomy has
        no vendor for the code. Quote escaping: ``'`` -> ``''``.
        """
        await self.authenticate()
        url = f"{self._vendorcard_url()}/filter"
        escaped_code = vendor_code.strip().replace("'", "''")
        payload = {
            "restriction": f"vendornumber='{escaped_code}'",
            "fields": ["name1", "vendornumber"],
            "limit": 1,
            "offset": 0,
        }
        try:
            response = await self.client.post(
                url,
                headers=self._container_headers(),
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyServiceError(
                "Maconomy vendor request failed"
            ) from exc

        try:
            pane = response.json()["panes"]["filter"]
            meta = pane["meta"]
            records = pane["records"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy vendor filter response"
            ) from exc
        if (
            not isinstance(meta, dict)
            or not isinstance(records, list)
            or not all(isinstance(record, dict) for record in records)
        ):
            raise MaconomyServiceError(
                "Invalid Maconomy vendor filter response"
            )

        row_count = meta.get("rowCount")
        if (
            isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or row_count != len(records)
        ):
            raise MaconomyServiceError(
                "Invalid Maconomy vendor filter response"
            )

        if not records:
            return None
        data = records[0].get("data")
        if not isinstance(data, dict):
            raise MaconomyServiceError(
                "Invalid Maconomy vendor filter response"
            )
        return {
            "vendornumber": str(data.get("vendornumber") or "").strip(),
            "name1": str(data.get("name1") or "").strip(),
        }
