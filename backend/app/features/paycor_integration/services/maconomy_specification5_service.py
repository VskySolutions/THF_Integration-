"""Service for creating Specification 5 records in Maconomy."""

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

SPECIFICATION5_FIELDS = (
    "specification5name",
    "description",
    "blocked",
    "dimensioncombnumber",
    "accountnumber",
    "locationname",
    "entityname",
    "projectname",
    "purposename",
    "specification1name",
    "specification2name",
    "specification3name",
    "specification4name",
    "specification6name",
    "specification7name",
    "specification8name",
    "specification9name",
    "specification10name",
    "localspec1name",
    "localspec2name",
    "localspec3name",
    "localspec4name",
    "localspec5name",
    "localspec6name",
    "localspec7name",
    "localspec8name",
    "localspec9name",
    "localspec10name",
    "overwriteaccount",
    "overwritelocation",
    "overwriteentity",
    "overwriteproject",
    "overwritepurpose",
    "overwritespec1",
    "overwritespec2",
    "overwritespec3",
    "overwritespec4",
    "overwritespec6",
    "overwritespec7",
    "overwritespec8",
    "overwritespec9",
    "overwritespec10",
    "overwritelocalspec1",
    "overwritelocalspec2",
    "overwritelocalspec3",
    "overwritelocalspec4",
    "overwritelocalspec5",
    "overwritelocalspec6",
    "overwritelocalspec7",
    "overwritelocalspec8",
    "overwritelocalspec9",
    "overwritelocalspec10",
    "statistic1",
    "statistic2",
    "statistic3",
    "statistic4",
    "remark1",
    "remark2",
    "remark3",
    "remark4",
    "remark5",
    "employeenumber1",
    "employeenumber2",
    "employeenumber3",
    "employeenumber4",
    "employeenumber5",
    "employeenumber6",
    "employeenumber7",
    "employeenumber8",
    "employeenumber9",
    "employeenumber10",
    "localaccountnumber",
    "overwritelocalaccount",
)


class MaconomySpecification5ServiceError(Exception):
    """Raised when a Maconomy specification5 operation fails."""


class MaconomySpecification5Service:
    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    async def create_specification5(
        self,
        *,
        employee_number: str,
        description: str,
    ) -> dict[str, Any]:
        """Create one Specification 5 record in Maconomy specification5 container."""
        normalized_employee_number = str(employee_number).strip()

        if not normalized_employee_number:
            raise MaconomySpecification5ServiceError(
                "Employee number is required for Specification 5"
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)

                instance_id, concurrency_token = (
                    await self._start_spec5_instance(
                        client, reconnect_token
                    )
                )

                initialized_data, concurrency_token = (
                    await self._initialize_spec5_card(
                        client,
                        reconnect_token,
                        instance_id,
                        concurrency_token,
                    )
                )

                spec5_payload = self._build_spec5_payload(
                    initialized_data=initialized_data,
                    employee_number=normalized_employee_number,
                    description=description,
                )

                return await self._submit_spec5_card(
                    client,
                    reconnect_token,
                    instance_id,
                    concurrency_token,
                    spec5_payload,
                )

        except httpx.RequestError as exc:
            request = getattr(exc, "request", None)
            request_url = (
                str(request.url)
                if request is not None
                else self.settings.maconomy_url
            )
            raise MaconomySpecification5ServiceError(
                "Unable to connect to Maconomy: "
                f"{type(exc).__name__} while calling {request_url}: {exc}"
            ) from exc

    @staticmethod
    def _build_spec5_payload(
        *,
        initialized_data: dict[str, Any],
        employee_number: str,
        description: str,
    ) -> dict[str, Any]:
        """Build specification 5 card payload filtering out read-only variables."""
        payload: dict[str, Any] = {}

        # Retain writable fields from initialized data or set defaults
        for field in SPECIFICATION5_FIELDS:
            if field in initialized_data:
                payload[field] = initialized_data[field]
            elif field.startswith("overwrite") or field == "blocked":
                payload[field] = False
            else:
                payload[field] = ""

        # Bind employee number and formatted description
        payload["specification5name"] = employee_number
        payload["description"] = description.strip()
        payload["blocked"] = False

        return payload

    def _spec5_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/"
            f"{shortname}/specification5"
        )

    async def _start_spec5_instance(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> tuple[str, str]:
        url = f"{self._spec5_url()}/instances"

        payload = {
            "panes": {
                "card": {
                    "fields": list(SPECIFICATION5_FIELDS),
                }
            }
        }

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
            raise MaconomySpecification5ServiceError(
                "Invalid Maconomy specification5 instance response"
            ) from exc

        concurrency_token = self._get_concurrency_token(response)
        return instance_id, concurrency_token

    async def _initialize_spec5_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
    ) -> tuple[dict[str, Any], str]:
        url = f"{self._spec5_url()}/instances/{instance_id}/data/panes/card/init"

        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token

        response = await client.post(
            url,
            headers=headers,
            json={},
        )
        response.raise_for_status()

        try:
            initialized_data = response.json()["data"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomySpecification5ServiceError(
                "Invalid Maconomy specification5 initialization response"
            ) from exc

        if not isinstance(initialized_data, dict):
            raise MaconomySpecification5ServiceError(
                "Invalid Maconomy specification5 initialization response format"
            )

        new_concurrency_token = self._get_concurrency_token(response)
        return dict(initialized_data), new_concurrency_token

    async def _submit_spec5_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        spec5_data: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"{self._spec5_url()}/instances/{instance_id}/data/panes/card"

        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token

        response = await client.post(
            url,
            headers=headers,
            json={"data": spec5_data},
        )

        if response.is_error:
            response_text = (
                response.text.strip()
                or "<empty Maconomy response body>"
            )
            raise MaconomySpecification5ServiceError(
                f"Maconomy rejected specification5 with HTTP {response.status_code}: "
                f"{response_text[:2000]}"
            )

        try:
            card = response.json()["panes"]["card"]
            records = card["records"]

            if card["meta"]["rowCount"] != 1 or len(records) != 1:
                raise MaconomySpecification5ServiceError(
                    "Unexpected Maconomy specification5 record count"
                )

            created_record = records[0]["data"]
        except MaconomySpecification5ServiceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomySpecification5ServiceError(
                "Invalid Maconomy specification5 creation response"
            ) from exc

        if not isinstance(created_record, dict):
            raise MaconomySpecification5ServiceError(
                "Invalid Maconomy specification5 creation response"
            )

        spec5_name = created_record.get("specification5name")
        if not isinstance(spec5_name, str) or not spec5_name.strip():
            raise MaconomySpecification5ServiceError(
                "Maconomy did not return specification5name"
            )

        return created_record

    async def _get_reconnect_token(
        self,
        client: httpx.AsyncClient,
    ) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        url = f"{self.settings.maconomy_url}/maconomy-api/auth/{shortname}/login"

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
                "Authorization": f"Basic {encoded_credentials}",
            },
        )
        response.raise_for_status()

        reconnect_token = response.headers.get("Maconomy-Reconnect", "").strip()

        if response.status_code != 204 or not reconnect_token:
            raise MaconomySpecification5ServiceError(
                "Maconomy authentication failed"
            )

        return reconnect_token

    @staticmethod
    def _get_concurrency_token(response: httpx.Response) -> str:
        concurrency_token = response.headers.get(
            "Maconomy-Concurrency-Control", ""
        ).strip()

        try:
            return str(uuid.UUID(concurrency_token))
        except (TypeError, ValueError) as exc:
            raise MaconomySpecification5ServiceError(
                "Invalid Maconomy concurrency token"
            ) from exc

    @staticmethod
    def _container_headers(reconnect_token: str) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }

