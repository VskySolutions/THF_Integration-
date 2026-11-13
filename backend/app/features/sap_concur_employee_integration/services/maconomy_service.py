"""Maconomy employee retrieval for the SAP Concur employee integration.

Retrieves active employees from the Maconomy `showemployeeshr` container so a
later phase can create/update them in SAP Concur. Authentication and container
headers mirror the existing `sap_concur_integration` Maconomy service.
"""

import base64
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings

AUTH_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.authentication+json; charset=utf-8; version=3.0"
)
CONTAINER_ACCEPT = (
    "application/vnd.deltek.maconomy.containers+json; charset=utf-8; version=9.0"
)
CONTAINER_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.containers+json; charset=UTF-8; version=9.0"
)

# Restriction, field list/order and page size are supplied by the integration
# owner in Req[#25] FR-8 and must be sent verbatim.
EMPLOYEE_RESTRICTION = (
    "DateEmployed le currentDate() and (DateEndEmployment gt currentDate() "
    "or DateEndEmployment = date(nulldate))"
)
EMPLOYEE_FIELDS = [
    "blocked",
    "companyname",
    "country",
    "dateemployed",
    "dateendemployment",
    "electronicmailaddress",
    "employeenumber",
    "initials",
    "instancekey",
    "name1",
    "position",
    "profileimage",
    # "superioremployee",
    "vendornumber",
    "name2",
    "name3",
    "zipcode",
    "postaldistrict",
    "dateemployed",
    "superioremployee",
    # "superioremployeename",
    "entityname",
    "specification4name",
    "firstname",
    "lastname",
    "middlename",
    "phone"
]
FILTER_LIMIT = 100
MAX_PAGES = 100


class MaconomyEmployeeServiceError(Exception):
    """Raised when Maconomy authentication or employee retrieval fails."""


class MaconomyEmployeeService:
    """Retrieve active Maconomy employees (read-only, no persistence)."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self.timeout = 60.0

    async def get_all_employees(self) -> list[dict[str, Any]]:
        """Return every active Maconomy employee across all filter pages."""
        try:
            if self.client is not None:
                return await self._collect_employees(self.client)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await self._collect_employees(client)
        except httpx.HTTPError as exc:
            raise MaconomyEmployeeServiceError(
                "Maconomy employee request failed"
            ) from exc

    async def _collect_employees(
        self, client: httpx.AsyncClient
    ) -> list[dict[str, Any]]:
        """Page through `showemployeeshr/filter` and collect unique employees."""
        reconnect_token = await self._get_reconnect_token(client)
        employees: list[dict[str, Any]] = []
        seen: set[str] = set()
        offset = 0

        for _ in range(MAX_PAGES):
            page = await self._filter_employees_page(
                client, reconnect_token, offset
            )
            for employee in page:
                key = str(
                    employee.get("instancekey")
                    or employee.get("employeenumber")
                    or ""
                ).strip()
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                employees.append(employee)

            if len(page) < FILTER_LIMIT:
                break
            offset += FILTER_LIMIT

        return employees

    async def _get_reconnect_token(self, client: httpx.AsyncClient) -> str:
        """Authenticate and return the Maconomy reconnect token."""
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
            raise MaconomyEmployeeServiceError("Maconomy authentication failed")
        return token

    async def _filter_employees_page(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        offset: int,
    ) -> list[dict[str, Any]]:
        """Fetch one page of employees from the showemployeeshr container."""
        payload = {
            "restriction": EMPLOYEE_RESTRICTION,
            "fields": EMPLOYEE_FIELDS,
            "limit": FILTER_LIMIT,
            "offset": offset,
        }
        try:
            response = await client.post(
                self._showemployeeshr_url(),
                headers=self._container_headers(reconnect_token),
                json=payload,
            )

            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyEmployeeServiceError(
                "Maconomy employee request failed"
            ) from exc

        return self._parse_page(response, expected_offset=offset)

    @staticmethod
    def _parse_page(
        response: httpx.Response, expected_offset: int
    ) -> list[dict[str, Any]]:
        """Validate a filter page and return the employee `data` dictionaries."""
        try:
            pane = response.json()["panes"]["filter"]
            records = pane["records"]
            row_count = pane["meta"]["rowCount"]
            row_offset = pane["meta"].get("rowOffset")
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise MaconomyEmployeeServiceError(
                "Invalid Maconomy employee response"
            ) from exc

        if (
            not isinstance(records, list)
            or isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or row_count != len(records)
            or (row_offset is not None and row_offset != expected_offset)
            or not all(
                isinstance(record, dict) and isinstance(record.get("data"), dict)
                for record in records
            )
        ):
            raise MaconomyEmployeeServiceError(
                "Invalid Maconomy employee response"
            )

        return [record["data"] for record in records]

    def _container_headers(self, reconnect_token: str) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }

    def _showemployeeshr_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/showemployeeshr/filter"
        )
