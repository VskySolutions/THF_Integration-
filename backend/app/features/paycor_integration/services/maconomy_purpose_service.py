"""Service for creating Purpose records in Maconomy."""

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

PURPOSE_FIELDS = (
    "purposename",
    "description",
    "blocked",
    "dimensioncombnumber",
    "accountnumber",
    "locationname",
    "entityname",
    "projectname",
    "specification1name",
    "specification2name",
    "specification3name",
    "specification4name",
    "specification5name",
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
    "overwritespec1",
    "overwritespec2",
    "overwritespec3",
    "overwritespec4",
    "overwritespec5",
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


class MaconomyPurposeServiceError(Exception):
    """Raised when a Maconomy purpose operation fails."""


class MaconomyPurposeService:
    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    async def create_purpose(
        self,
        *,
        employee_number: str,
        description: str,
    ) -> dict[str, Any]:
        """Create one Purpose record in Maconomy purpose container."""
        normalized_employee_number = str(employee_number).strip()

        if not normalized_employee_number:
            raise MaconomyPurposeServiceError(
                "Employee number is required for Purpose"
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)

                instance_id, concurrency_token = (
                    await self._start_purpose_instance(
                        client, reconnect_token
                    )
                )

                initialized_data, concurrency_token = (
                    await self._initialize_purpose_card(
                        client,
                        reconnect_token,
                        instance_id,
                        concurrency_token,
                    )
                )

                purpose_payload = self._build_purpose_payload(
                    initialized_data=initialized_data,
                    employee_number=normalized_employee_number,
                    description=description,
                )

                return await self._submit_purpose_card(
                    client,
                    reconnect_token,
                    instance_id,
                    concurrency_token,
                    purpose_payload,
                )

        except httpx.RequestError as exc:
            request = getattr(exc, "request", None)
            request_url = (
                str(request.url)
                if request is not None
                else self.settings.maconomy_url
            )
            raise MaconomyPurposeServiceError(
                "Unable to connect to Maconomy: "
                f"{type(exc).__name__} while calling {request_url}: {exc}"
            ) from exc

    @staticmethod
    def _build_purpose_payload(
        *,
        initialized_data: dict[str, Any],
        employee_number: str,
        description: str,
    ) -> dict[str, Any]:
        """Build purpose card payload filtering out read-only variables."""
        payload: dict[str, Any] = {}

        # Retain writable fields from initialized data or set defaults
        for field in PURPOSE_FIELDS:
            if field in initialized_data:
                payload[field] = initialized_data[field]
            elif field.startswith("overwrite") or field == "blocked":
                payload[field] = False
            else:
                payload[field] = ""

        # Bind employee number and formatted description
        payload["purposename"] = employee_number
        payload["description"] = description.strip()
        payload["blocked"] = False

        return payload

    def _purpose_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/"
            f"{shortname}/purpose"
        )

    async def _start_purpose_instance(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> tuple[str, str]:
        url = f"{self._purpose_url()}/instances"

        payload = {
            "panes": {
                "card": {
                    "fields": list(PURPOSE_FIELDS),
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
            raise MaconomyPurposeServiceError(
                "Invalid Maconomy purpose instance response"
            ) from exc

        concurrency_token = self._get_concurrency_token(response)
        return instance_id, concurrency_token

    async def _initialize_purpose_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
    ) -> tuple[dict[str, Any], str]:
        url = f"{self._purpose_url()}/instances/{instance_id}/data/panes/card/init"

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
            raise MaconomyPurposeServiceError(
                "Invalid Maconomy purpose initialization response"
            ) from exc

        if not isinstance(initialized_data, dict):
            raise MaconomyPurposeServiceError(
                "Invalid Maconomy purpose initialization response format"
            )

        new_concurrency_token = self._get_concurrency_token(response)
        return dict(initialized_data), new_concurrency_token

    async def _submit_purpose_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        purpose_data: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"{self._purpose_url()}/instances/{instance_id}/data/panes/card"

        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token

        response = await client.post(
            url,
            headers=headers,
            json={"data": purpose_data},
        )

        if response.is_error:
            response_text = (
                response.text.strip()
                or "<empty Maconomy response body>"
            )
            raise MaconomyPurposeServiceError(
                f"Maconomy rejected purpose with HTTP {response.status_code}: "
                f"{response_text[:2000]}"
            )

        try:
            card = response.json()["panes"]["card"]
            records = card["records"]

            if card["meta"]["rowCount"] != 1 or len(records) != 1:
                raise MaconomyPurposeServiceError(
                    "Unexpected Maconomy purpose record count"
                )

            created_record = records[0]["data"]
        except MaconomyPurposeServiceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyPurposeServiceError(
                "Invalid Maconomy purpose creation response"
            ) from exc

        if not isinstance(created_record, dict):
            raise MaconomyPurposeServiceError(
                "Invalid Maconomy purpose creation response"
            )

        purpose_name = created_record.get("purposename")
        if not isinstance(purpose_name, str) or not purpose_name.strip():
            raise MaconomyPurposeServiceError(
                "Maconomy did not return purposename"
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
            raise MaconomyPurposeServiceError(
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
            raise MaconomyPurposeServiceError(
                "Invalid Maconomy concurrency token"
            ) from exc

    @staticmethod
    def _container_headers(reconnect_token: str) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }

