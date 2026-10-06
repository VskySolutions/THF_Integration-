"""Maconomy job discovery for the client-scoped CCH/XCM integration."""

import base64
from calendar import month_abbr, month_name, monthrange
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID

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

    async def update_cch_processing_results(
        self,
        jobs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Write date5 and an optional task ID to each processed Maconomy job."""
        await self.authenticate()
        updated_jobs: list[dict[str, Any]] = []
        for job in jobs:
            updated_job = dict(job)
            client_creation = job.get("cchclientcreation")
            if (
                not isinstance(client_creation, dict)
                or client_creation.get("status") != "created"
            ):
                updated_job["maconomywritebackstatus"] = "skipped"
                updated_jobs.append(updated_job)
                continue

            try:
                job_number = self._required_string(
                    job.get("jobnumber"), "jobnumber"
                )
                period_end_date = self._required_string(
                    job.get("periodenddate"), "periodenddate"
                )
                source_version = self._parse_version(job.get("versionnumber"))

                task_id: str | None = None
                task_creation = job.get("cchtaskcreation")
                if (
                    isinstance(task_creation, dict)
                    and task_creation.get("status") == "created"
                ):
                    task_id = self._required_string(
                        task_creation.get("taskid"), "CCH task ID"
                    )

                saved_version = await self._update_job_cch_log(
                    job_number=job_number,
                    source_version=source_version,
                    period_end_date=period_end_date,
                    task_id=task_id,
                )
                updated_job["date5"] = period_end_date
                if task_id is not None:
                    updated_job["text20"] = task_id
                updated_job["versionnumber"] = saved_version
                updated_job["maconomywritebackstatus"] = "updated"
            except Exception as exc:
                updated_job["maconomywritebackstatus"] = "failed"
                updated_job["maconomywritebackerror"] = (
                    self._safe_update_error_message(exc)
                )
            updated_jobs.append(updated_job)
        return updated_jobs

    async def _update_job_cch_log(
        self,
        *,
        job_number: str,
        source_version: int,
        period_end_date: str,
        task_id: str | None,
    ) -> int:
        job, instance_id, concurrency_token = await self._bind_job(job_number)
        current_version = self._parse_version(job.get("versionnumber"))
        if current_version != source_version:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} changed before its CCH log could be saved"
            )

        if task_id is not None:
            current_task_id = job.get("text20")
            if current_task_id is not None and (
                not isinstance(current_task_id, str) or current_task_id.strip()
            ):
                raise MaconomyServiceError(
                    f"Maconomy job {job_number} already has a text20 mapping"
                )

        maconomy_period_end_date = datetime.strptime(
            period_end_date, "%m/%d/%Y"
        ).strftime("%Y-%m-%d")
        data: dict[str, Any] = {"date5": maconomy_period_end_date}
        if task_id is not None:
            data["text20"] = task_id

        await self._post_job_request(
            f"/instances/{instance_id}/data/panes/card/0",
            {"data": data},
            concurrency_token=concurrency_token,
        )

        saved_job, _, _ = await self._bind_job(job_number)
        saved_version = self._parse_version(saved_job.get("versionnumber"))
        if saved_version != source_version + 1:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} version did not increase by one"
            )
        if str(saved_job.get("date5", "")).strip() != maconomy_period_end_date:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} date5 write could not be verified"
            )
        if task_id is not None and str(saved_job.get("text20", "")).strip() != task_id:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} text20 write could not be verified"
            )
        return saved_version

    async def _bind_job(
        self, job_number: str
    ) -> tuple[dict[str, Any], str, str]:
        instance_response = await self._post_job_request(
            "/instances",
            {
                "panes": {
                    "card": {
                        "fields": [
                            "jobnumber",
                            "versionnumber",
                            "text20",
                            "date5",
                        ]
                    }
                }
            },
        )
        try:
            instance_id_value = instance_response.json()["meta"][
                "containerInstanceId"
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy instance response") from exc

        instance_id = self._response_uuid(
            instance_id_value, "containerInstanceId"
        )
        concurrency_token = self._response_uuid(
            instance_response.headers.get("Maconomy-Concurrency-Control"),
            "Maconomy-Concurrency-Control",
        )
        bind_response = await self._post_job_request(
            f"/instances/{instance_id}/data;jobnumber={quote(job_number, safe='')}",
            {},
            concurrency_token=concurrency_token,
        )
        bound_token = self._response_uuid(
            bind_response.headers.get("Maconomy-Concurrency-Control"),
            "Maconomy-Concurrency-Control",
        )
        records = self._read_pane_records(bind_response, "card")
        if len(records) != 1 or str(records[0].get("jobnumber")) != job_number:
            raise MaconomyServiceError(f"Maconomy job {job_number} was not found")
        return records[0], instance_id, bound_token

    async def _post_job_request(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        concurrency_token: str | None = None,
    ) -> httpx.Response:
        headers = self._container_headers()
        if concurrency_token is not None:
            headers["Maconomy-Concurrency-Control"] = concurrency_token
        response = await self.client.post(
            f"{self._jobs_url()}{path}",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response

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
    def _read_pane_records(
        response: httpx.Response,
        pane_name: str,
    ) -> list[dict[str, Any]]:
        try:
            pane = response.json()["panes"][pane_name]
            records = [record["data"] for record in pane["records"]]
            row_count = pane["meta"]["rowCount"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                f"Invalid Maconomy {pane_name} response"
            ) from exc
        if (
            isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or row_count != len(records)
            or not all(isinstance(record, dict) for record in records)
        ):
            raise MaconomyServiceError(f"Invalid Maconomy {pane_name} response")
        return records

    @staticmethod
    def _response_uuid(value: Any, field_name: str) -> str:
        try:
            return str(UUID(value))
        except (AttributeError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                f"Invalid Maconomy {field_name} response"
            ) from exc

    @staticmethod
    def _parse_version(value: Any) -> int:
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MaconomyServiceError("Invalid Maconomy versionnumber")
        return value

    @staticmethod
    def _required_string(value: Any, field_name: str) -> str:
        if value is None or not str(value).strip():
            raise MaconomyServiceError(f"Maconomy {field_name} is required")
        return str(value).strip()

    @staticmethod
    def _safe_update_error_message(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            return f"Maconomy update failed with HTTP {exc.response.status_code}"
        if isinstance(exc, httpx.RequestError):
            return "Maconomy update failed or timed out"
        return str(exc)

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

    def _jobs_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/jobs"
        )
