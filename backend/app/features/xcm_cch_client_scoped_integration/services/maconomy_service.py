"""Maconomy job discovery for the client-scoped CCH/XCM integration."""

import base64
from datetime import date, timedelta
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
JOB_FIELDS = [
    # New
    "jobnumber",
    "jobname",
    "description1",
    "customernumber",
    "name1",
    "telephone",
    "electronicmailaddress",
    "projectmanagernumber",
    "projectmanagername",
    "locationname",
    "specification2name",
    "closed",
    "template",
    "theyear",
    "createddate",
    "changeddate",
    "employeenumber6",        
    "specification1name",        
    "specification5name",
    "text20",
    "date5",
    "versionnumber",
]
JOB_FILTER_LIMIT = 5000


class MaconomyServiceError(Exception):
    """Raised when Maconomy authentication or job discovery fails."""


class MaconomyService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self._reconnect_token: str | None = None

    async def authenticate(self) -> None:
        """Authenticate once per service instance and retain the reconnect token."""
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
            raise MaconomyServiceError("Maconomy authentication request failed") from exc

        token = response.headers.get("Maconomy-Reconnect", "").strip()
        if response.status_code != 204 or not token:
            raise MaconomyServiceError("Invalid Maconomy authentication response")
        self._reconnect_token = token

    async def get_syncable_tax_jobs(
        self,
        jobnumbers: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch one batch of eligible jobs from Maconomy."""
        selected_jobnumbers = jobnumbers or None
        await self.authenticate()

        shortname = quote(self.settings.maconomy_shortname, safe="")
        url = (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/jobs/filter"
        )
        restriction = self._job_restriction(selected_jobnumbers)
        requested_numbers = (
            set(selected_jobnumbers) if selected_jobnumbers is not None else None
        )
        try:
            response = await self.client.post(
                url,
                headers=self._container_headers(),
                json={
                    "restriction": restriction,
                    "fields": JOB_FIELDS,
                    "limit": JOB_FILTER_LIMIT,
                    "offset": 0,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy job request failed") from exc

        records = self._read_filter_records(response)
        return [
            record
            for record in records
            if self._is_syncable_tax_job(record)
            and (
                requested_numbers is None
                or str(record.get("jobnumber")) in requested_numbers
            )
        ]

    @staticmethod
    def _job_restriction(
        jobnumbers: list[str] | None,
    ) -> str:
        restriction = (
            "template=false and locationname='2' "
            "and closed=false and text20=''"
        )
        if not jobnumbers:
            yesterday = date.today() - timedelta(days=1)
            restriction += (
                " and (createddate>="
                f"date({yesterday.year},{yesterday.month},{yesterday.day-1}))"
            )
        else:
            numbers = list(dict.fromkeys(jobnumbers))
            conditions = []
            for number in numbers:
                escaped_number = number.replace("'", "''")
                conditions.append(f"jobnumber='{escaped_number}'")
            restriction += f" and ({' or '.join(conditions)})"
        return restriction

    def _container_headers(self) -> dict[str, str]:
        if self._reconnect_token is None:
            raise MaconomyServiceError("Maconomy has not been authenticated")
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {self._reconnect_token}",
        }

    @staticmethod
    def _read_filter_records(response: httpx.Response) -> list[dict[str, Any]]:
        try:
            pane = response.json()["panes"]["filter"]
            meta = pane["meta"]
            row_count = meta["rowCount"]
            row_offset = meta.get("rowOffset")
            records = [record["data"] for record in pane["records"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy filter response") from exc
        if (
            isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or row_count != len(records)
            or row_offset is not None
            and row_offset != 0
            or not all(isinstance(record, dict) for record in records)
        ):
            raise MaconomyServiceError("Invalid Maconomy filter response")
        return records

    @staticmethod
    def _is_syncable_tax_job(record: dict[str, Any]) -> bool:
        location_name = record.get("locationname")
        task_internal_id = record.get("text20")
        return (
            record.get("template") is False
            and record.get("closed") is False
            and str(location_name) == "2"
            and "text20" in record
            and (task_internal_id is None or task_internal_id == "")
        )
