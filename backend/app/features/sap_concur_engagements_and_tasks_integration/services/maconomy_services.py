"""Maconomy retrieval of engagements (jobs) and their associated tasks.

Auth/header/filter helpers are copied from
``xcm_cch_client_scoped_integration/services/maconomy_service.py`` (repo
convention: each feature owns its Maconomy auth code — no cross-feature
imports). The two-call recipe (``jobs/filter`` -> collect tasklists ->
``api_tasks/filter``) mirrors
``sap_concur_integration/services/maconomy_services.py``.
"""

import base64
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.features.sap_concur_engagements_and_tasks_integration.constants import (
    DEFAULT_JOBS_LIMIT,
    JOBS_FILTER_FIELDS,
    TASK_FILTER_FIELDS,
    TASKS_FILTER_LIMIT,
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
    """Raised when Maconomy authentication or container retrieval fails."""


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
            or isinstance(row_offset, bool)
            or row_offset is not None
            and not isinstance(row_offset, int)
            or not all(isinstance(record, dict) for record in records)
        ):
            raise MaconomyServiceError("Invalid Maconomy filter response")
        return records

    def _jobs_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return f"{self.settings.maconomy_url}/maconomy-api/containers/{shortname}/jobs"

    def _api_tasks_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/api_tasks"
        )

    @staticmethod
    def _build_or_restriction(field: str, values: list[str]) -> str:
        escaped = [v.replace("'", "''") for v in values if v and v.strip()]
        return " or ".join(f"{field}='{v}'" for v in escaped)

    async def get_engagements(
        self,
        limit: int = DEFAULT_JOBS_LIMIT,
        offset: int = 0,
        *,
        today: date | None = None,
    ) -> list[dict[str, Any]]:
        """ONE jobs/filter call returning engagement (job) records.

        Restricted to open, non-template jobs created within the current
        two-day window (yesterday..today). Returns raw records including
        ``jobnumber``, ``jobname``, ``name1`` and ``tasklist``; response
        shaping is done by ``engagement_mapper.build_engagements_payload``.
        """
        current_date = today or date.today()
        start_date = current_date - timedelta(days=1)
        restriction = (
            "template=false "
            "and closed=false "
            "and createddate>="
            f"date({start_date.year},{start_date.month},{start_date.day}) "
            "and createddate<="
            f"date({current_date.year},{current_date.month},{current_date.day})"
        )
        payload: dict[str, Any] = {
            "restriction": restriction,
            "fields": JOBS_FILTER_FIELDS,
            "limit": limit,
            "offset": offset,
        }
        try:
            response = await self.client.post(
                f"{self._jobs_url()}/filter",
                headers=self._container_headers(),
                json=payload,
            )
            print(f"Maconomy jobs/filter response: {response.text}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyServiceError(
                f"Maconomy jobs request failed: {exc}"
            ) from exc
        return self._read_filter_records(response)

    async def get_tasks_by_task_lists(
        self,
        task_lists: list[str],
        *,
        today: date | None = None,
    ) -> list[dict[str, Any]]:
        """ONE api_tasks/filter call for all given task lists.

        Returns raw task records (taskname, tasklist, description,
        activitynumber, activitytype). Restricted to approved tasks
        (``approved=true``) whose ``approvaldate`` falls within the
        current two-day window (yesterday..today). No expense-eligibility
        filters are applied.
        """
        if not task_lists:
            return []
        or_clause = self._build_or_restriction("tasklist", task_lists)
        current_date = today or date.today()
        start_date = current_date - timedelta(days=1)
        restriction = (
            f"({or_clause}) "
            "and approved=true "
            
        )
        payload: dict[str, Any] = {
            "restriction": restriction,
            "fields": TASK_FILTER_FIELDS,
            "limit": TASKS_FILTER_LIMIT,
            "offset": 0,
        }
        try:
            response = await self.client.post(
                f"{self._api_tasks_url()}/filter",
                headers=self._container_headers(),
                json=payload,
            )
            print(f"Maconomy api_tasks/filter response: {response.text}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyServiceError(
                f"Maconomy tasks request failed: {exc}"
            ) from exc
        return self._read_filter_records(response)
