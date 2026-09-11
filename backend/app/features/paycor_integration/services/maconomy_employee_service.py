"""Service for reading and creating employees in Maconomy."""

import base64
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.features.paycor_integration.mappers import (
    map_paycor_employee_to_maconomy,
)

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

EMPLOYEE_FIELDS = (
    "employeenumber",
    "name1",
    "country",
    "dateemployed",
    "electronicmailaddress",
    "position",
    "superioremployee",
    "instancekey",
    "text10",
)

EMPLOYEE_LOOKUP_FIELDS = (
    "employeenumber",
)

EMPLOYEE_FILTER_PAGE_SIZE = 1000


class MaconomyEmployeeServiceError(Exception):
    """Raised when a Maconomy employee operation fails."""


class MaconomyEmployeeService:
    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0
        self.max_filter_pages = 1000

    async def get_all_employee_numbers(
        self,
    ) -> set[str]:
        """Return all existing Maconomy employee numbers."""

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                reconnect_token = (
                    await self._get_reconnect_token(
                        client
                    )
                )

                return await (
                    self._get_paginated_employee_numbers(
                        client,
                        reconnect_token,
                    )
                )

        except httpx.HTTPError as exc:
            raise MaconomyEmployeeServiceError(
                "Unable to retrieve Maconomy employees"
            ) from exc

    async def create_employee(
        self,
        paycor_employee_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create one Maconomy employee from one Paycor employee."""

        try:
            employee_payload = (
                map_paycor_employee_to_maconomy(
                    paycor_employee_data
                )
            )

        except ValueError as exc:
            raise MaconomyEmployeeServiceError(
                str(exc)
            ) from exc

        mapped_data = employee_payload.get("data")

        if not isinstance(mapped_data, dict):
            raise MaconomyEmployeeServiceError(
                "Invalid Maconomy employee payload"
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
                    await self._start_employee_creation(
                        client,
                        reconnect_token,
                    )
                )

                initialized_data, concurrency_token = (
                    await self._initialize_employee_card(
                        client,
                        reconnect_token,
                        instance_id,
                        concurrency_token,
                    )
                )

                employee_data = {
                    **initialized_data,
                    **mapped_data,
                }

                return await self._submit_employee_card(
                    client,
                    reconnect_token,
                    instance_id,
                    concurrency_token,
                    employee_data,
                )

        except httpx.HTTPStatusError as exc:
            response_text = exc.response.text.strip()

            raise MaconomyEmployeeServiceError(
                "Maconomy employee request failed "
                f"with HTTP {exc.response.status_code}: "
                f"{response_text[:1000]}"
            ) from exc

        except httpx.RequestError as exc:
            raise MaconomyEmployeeServiceError(
                "Unable to connect to Maconomy"
            ) from exc

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
            raise MaconomyEmployeeServiceError(
                "Maconomy authentication failed"
            )

        return reconnect_token

    async def _get_paginated_employee_numbers(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> set[str]:
        url = f"{self._employees_url()}/filter"

        headers = self._container_headers(
            reconnect_token
        )

        employee_numbers: set[str] = set()
        offset = 0

        for _ in range(self.max_filter_pages):
            payload = {
                "fields": list(
                    EMPLOYEE_LOOKUP_FIELDS
                ),
                "offset": offset,
                "limit": EMPLOYEE_FILTER_PAGE_SIZE,
            }

            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

            try:
                filter_pane = (
                    response.json()["panes"]["filter"]
                )
                meta = filter_pane["meta"]
                records = filter_pane["records"]

            except (
                KeyError,
                TypeError,
                ValueError,
            ) as exc:
                raise MaconomyEmployeeServiceError(
                    "Invalid Maconomy employee "
                    "filter response"
                ) from exc

            if (
                not isinstance(meta, dict)
                or not isinstance(records, list)
            ):
                raise MaconomyEmployeeServiceError(
                    "Invalid Maconomy employee "
                    "filter response"
                )

            row_total_count = (
                self._parse_optional_filter_count(
                    meta.get("rowTotalCount"),
                    "rowTotalCount",
                )
            )

            row_count = self._parse_filter_count(
                meta.get("rowCount"),
                "rowCount",
            )

            row_offset = self._parse_filter_count(
                meta.get("rowOffset"),
                "rowOffset",
            )

            if row_count != len(records):
                raise MaconomyEmployeeServiceError(
                    "Maconomy employee filter returned "
                    "an inconsistent row count"
                )

            for record in records:
                if not isinstance(record, dict):
                    raise MaconomyEmployeeServiceError(
                        "Invalid Maconomy employee record"
                    )

                employee_data = record.get("data")

                if not isinstance(employee_data, dict):
                    raise MaconomyEmployeeServiceError(
                        "Invalid Maconomy employee record"
                    )

                employee_number = employee_data.get(
                    "employeenumber"
                )

                if employee_number is None:
                    continue

                normalized_employee_number = str(
                    employee_number
                ).strip()

                if normalized_employee_number:
                    employee_numbers.add(
                        normalized_employee_number
                    )

            next_offset = row_offset + row_count

            if (
                row_total_count is not None
                and next_offset >= row_total_count
            ):
                return employee_numbers

            if row_count == 0:
                if row_total_count is None:
                    return employee_numbers

                raise MaconomyEmployeeServiceError(
                    "Maconomy employee filter ended "
                    "before all records were returned"
                )

            if next_offset <= offset:
                raise MaconomyEmployeeServiceError(
                    "Maconomy employee filter pagination "
                    "did not advance"
                )

            offset = next_offset

        raise MaconomyEmployeeServiceError(
            "Maconomy employee filter exceeded "
            "the maximum page limit"
        )

    async def _start_employee_creation(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> tuple[str, str]:
        url = f"{self._employees_url()}/instances"

        payload = {
            "panes": {
                "card": {
                    "fields": list(EMPLOYEE_FIELDS),
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
            raise MaconomyEmployeeServiceError(
                "Invalid Maconomy employee "
                "instance response"
            ) from exc

        concurrency_token = (
            self._get_concurrency_token(response)
        )

        return instance_id, concurrency_token

    async def _initialize_employee_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
    ) -> tuple[dict[str, Any], str]:
        url = (
            f"{self._employees_url()}/instances/"
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
            raise MaconomyEmployeeServiceError(
                "Invalid Maconomy employee "
                "initialization response"
            ) from exc

        if not isinstance(initialized_data, dict):
            raise MaconomyEmployeeServiceError(
                "Invalid Maconomy employee "
                "initialization response"
            )

        instance_key = initialized_data.get(
            "instancekey"
        )

        if (
            not isinstance(instance_key, str)
            or not instance_key.strip()
        ):
            raise MaconomyEmployeeServiceError(
                "Maconomy employee instance key "
                "is missing"
            )

        new_concurrency_token = (
            self._get_concurrency_token(response)
        )

        return (
            dict(initialized_data),
            new_concurrency_token,
        )

    async def _submit_employee_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        employee_data: dict[str, Any],
    ) -> dict[str, Any]:
        url = (
            f"{self._employees_url()}/instances/"
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
            json={"data": employee_data},
        )
        response.raise_for_status()

        try:
            card = response.json()["panes"]["card"]
            records = card["records"]

            if (
                card["meta"]["rowCount"] != 1
                or len(records) != 1
            ):
                raise MaconomyEmployeeServiceError(
                    "Unexpected Maconomy employee "
                    "record count"
                )

            created_employee = records[0]["data"]

        except MaconomyEmployeeServiceError:
            raise

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise MaconomyEmployeeServiceError(
                "Invalid Maconomy employee "
                "creation response"
            ) from exc

        if not isinstance(created_employee, dict):
            raise MaconomyEmployeeServiceError(
                "Invalid Maconomy employee "
                "creation response"
            )

        employee_number = created_employee.get(
            "employeenumber"
        )

        if (
            not isinstance(employee_number, str)
            or not employee_number.strip()
        ):
            raise MaconomyEmployeeServiceError(
                "Maconomy did not return an "
                "employee number"
            )

        return created_employee

    def _employees_url(self) -> str:
        shortname = quote(
            self.settings.maconomy_shortname,
            safe="",
        )

        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/"
            f"{shortname}/employees"
        )

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
            raise MaconomyEmployeeServiceError(
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

    @staticmethod
    def _parse_filter_count(
        value: Any,
        field_name: str,
    ) -> int:
        if isinstance(value, bool):
            raise MaconomyEmployeeServiceError(
                "Invalid Maconomy employee filter "
                f"{field_name}: {value!r}"
            )

        if isinstance(value, int) and value >= 0:
            return value

        if isinstance(value, str):
            normalized_value = value.strip()

            if normalized_value.isdigit():
                return int(normalized_value)

        raise MaconomyEmployeeServiceError(
            "Invalid Maconomy employee filter "
            f"{field_name}: {value!r}"
        )


    @staticmethod
    def _parse_optional_filter_count(
        value: Any,
        field_name: str,
    ) -> int | None:
        if value is None:
            return None

        if isinstance(value, bool):
            raise MaconomyEmployeeServiceError(
                "Invalid Maconomy employee filter "
                f"{field_name}: {value!r}"
            )

        if isinstance(value, int):
            if value == -1:
                return None

            if value >= 0:
                return value

        if isinstance(value, str):
            normalized_value = value.strip()

            if normalized_value in {"", "-1"}:
                return None

            if normalized_value.isdigit():
                return int(normalized_value)

            if (
                normalized_value.endswith("+")
                and normalized_value[:-1].isdigit()
            ):
                return None

        raise MaconomyEmployeeServiceError(
            "Invalid Maconomy employee filter "
            f"{field_name}: {value!r}"
        )