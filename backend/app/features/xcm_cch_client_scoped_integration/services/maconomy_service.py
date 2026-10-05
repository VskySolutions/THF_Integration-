"""Maconomy job discovery for the client-scoped CCH/XCM integration."""

import base64
from calendar import month_abbr, month_name, monthrange
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
CUSTOMER_FIELDS = ["customernumber", "name1", "fiscalyearendmonth"]
EMPLOYEE_FIELDS = ["employeenumber", "electronicmailaddress"]
SPECIFICATION2_FIELDS = ["specification2name", "description"]
SPECIFICATION1_FIELDS = ["specification1name", "description"]
REFERENCE_FILTER_LIMIT = 5000
SPECIFICATION_FILTER_LIMIT = 1000
MONTH_NAME_TO_NUMBER = {
    name.casefold(): month_number
    for month_number, name in enumerate(month_name)
    if name
}
MONTH_NAME_TO_NUMBER.update(
    {
        name.casefold(): month_number
        for month_number, name in enumerate(month_abbr)
        if name
    }
)


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

    async def get_client_reference_records(
        self,
        jobs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Fetch Maconomy records needed to enrich the selected jobs."""
        if not jobs:
            return {
                "customer_numbers": [],
                "employee_numbers": [],
                "customers": [],
                "employees": [],
                "specification2": [],
                "specification1": [],
            }

        customer_numbers = self._unique_job_values(jobs, "customernumber")
        employee_numbers = self._unique_job_values(
            jobs,
            "projectmanagernumber",
            "specification5name",
            "employeenumber6",
        )

        customers = (
            await self._filter_container(
                "customercard",
                CUSTOMER_FIELDS,
                limit=REFERENCE_FILTER_LIMIT,
                restriction=self._number_restriction(
                    "customernumber", customer_numbers
                ),
            )
            if customer_numbers
            else []
        )
        employees = (
            await self._filter_container(
                "employees",
                EMPLOYEE_FIELDS,
                limit=REFERENCE_FILTER_LIMIT,
                restriction=self._number_restriction(
                    "employeenumber", employee_numbers
                ),
            )
            if employee_numbers
            else []
        )
        specification2 = await self._filter_container(
            "specification2",
            SPECIFICATION2_FIELDS,
            limit=SPECIFICATION_FILTER_LIMIT,
        )
        specification1 = await self._filter_container(
            "specification1",
            SPECIFICATION1_FIELDS,
            limit=SPECIFICATION_FILTER_LIMIT,
        )
        return {
            "customer_numbers": customer_numbers,
            "employee_numbers": employee_numbers,
            "customers": customers,
            "employees": employees,
            "specification2": specification2,
            "specification1": specification1,
        }

    @staticmethod
    def join_client_reference_records(
        jobs: list[dict[str, Any]],
        reference_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Add customer, specification, and employee details to each job."""
        def index(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
            lookup: dict[str, dict[str, Any]] = {}
            for record in records:
                value = record.get(key)
                if value is not None and str(value).strip():
                    lookup.setdefault(str(value).strip(), record)
            return lookup

        def match(
            lookup: dict[str, dict[str, Any]], value: Any, field: str
        ) -> Any:
            if value is None:
                return None
            return lookup.get(str(value).strip(), {}).get(field)

        customers = index(reference_data["customers"], "customernumber")
        employees = index(reference_data["employees"], "employeenumber")
        specification1 = index(reference_data["specification1"], "specification1name")
        specification2 = index(reference_data["specification2"], "specification2name")

        enriched_jobs: list[dict[str, Any]] = []
        for job in jobs:
            fiscal_year_end_month = match(
                customers, job.get("customernumber"), "fiscalyearendmonth"
            )
            enriched_jobs.append({
                **job,
                "fiscalyearendmonth": fiscal_year_end_month,
                "periodenddate": MaconomyService._calculate_period_end_date(
                    job.get("theyear"), fiscal_year_end_month
                ),
                "specification1_description": match(
                    specification1, job.get("specification1name"), "description"
                ),
                "specification2_description": match(
                    specification2, job.get("specification2name"), "description"
                ),
                "projectmanager_email": match(
                    employees, job.get("projectmanagernumber"), "electronicmailaddress"
                ),
                "employee6_email": match(
                    employees, job.get("employeenumber6"), "electronicmailaddress"
                ),
                "spec5_email": match(
                    employees, job.get("specification5name"), "electronicmailaddress"
                ),
            })
        return enriched_jobs

    @staticmethod
    def _calculate_period_end_date(year: Any, month: Any) -> str | None:
        if isinstance(year, bool) or isinstance(month, bool):
            return None

        try:
            numeric_year = int(year)
            normalized_month = str(month).strip().casefold()
            numeric_month = MONTH_NAME_TO_NUMBER.get(
                normalized_month,
                int(normalized_month) if normalized_month.isdigit() else 0,
            )
            last_day = monthrange(numeric_year, numeric_month)[1]
            period_end_date = date(numeric_year, numeric_month, last_day)
        except (TypeError, ValueError):
            return None

        return period_end_date.strftime("%m/%d/%Y")

    async def _filter_container(
        self,
        container: str,
        fields: list[str],
        *,
        limit: int,
        restriction: str | None = None,
    ) -> list[dict[str, Any]]:
        await self.authenticate()
        shortname = quote(self.settings.maconomy_shortname, safe="")
        payload: dict[str, Any] = {
            "fields": fields,
            "limit": limit,
            "offset": 0,
        }
        if restriction is not None:
            payload["restriction"] = restriction
        try:
            response = await self.client.post(
                f"{self.settings.maconomy_url}/maconomy-api/containers/"
                f"{shortname}/{container}/filter",
                headers=self._container_headers(),
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyServiceError(
                f"Maconomy {container} request failed"
            ) from exc
        return self._read_filter_records(response)

    @staticmethod
    def _unique_job_values(
        jobs: list[dict[str, Any]],
        *fields: str,
    ) -> list[str]:
        numbers: list[str] = []
        seen: set[str] = set()
        for job in jobs:
            for field in fields:
                value = job.get(field)
                if value is None:
                    continue
                number = str(value).strip()
                if number and number not in seen:
                    numbers.append(number)
                    seen.add(number)
        return numbers

    @staticmethod
    def _number_restriction(field: str, numbers: list[str]) -> str:
        conditions = []
        for number in numbers:
            escaped_number = number.replace("'", "''")
            conditions.append(f"{field}='{escaped_number}'")
        return f"({' or '.join(conditions)})"

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
                f"date({yesterday.year},{yesterday.month - 1},{yesterday.day}))"
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
