import base64
from calendar import month_abbr, month_name, monthrange
from datetime import date, timedelta
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

SYNCABLE_JOB_FIELDS = [
    "jobnumber",
    "locationname",
    "customernumber",
    "specification2name",
    "theyear",
    "text20",
    "date5",
    "createddate",
    "changeddate",
    "closed",
    "template",
    "versionnumber",
]

CUSTOMER_FIELDS = [
    "customernumber",
    "fiscalyearendmonth",
]

SPECIFICATION2_FIELDS = [
    "specification2name",
    "description",
]

DEFAULT_TASK_TYPE = "Tax - 1041 Fiduciary"

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
    """Raised when syncable jobs cannot be retrieved from Maconomy."""


class MaconomyService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    async def get_syncable_tax_jobs(self) -> list[dict[str, Any]]:
        """Return unsynced open TAX jobs created today or yesterday."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)
                jobs = await self._get_syncable_tax_job_records(
                    client,
                    reconnect_token,
                )
                return await self._add_customer_fiscal_year_end_month(
                    client,
                    reconnect_token,
                    jobs,
                )
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy request failed") from exc

    async def update_cch_task_mappings(
        self,
        jobs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Write resolved CCH task IDs and period-end dates to Maconomy jobs."""
        if not jobs:
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)
                updated_jobs: list[dict[str, Any]] = []
                for job in jobs:
                    updated_job = dict(job)
                    resolution = job.get("cchtaskresolution")
                    print("-"*50)
                    print(resolution)
                    if isinstance(resolution, dict) and resolution.get(
                        "status"
                    ) in {"failed", "manual_review"}:
                        updated_job["maconomywritebackstatus"] = "skipped"
                        updated_jobs.append(updated_job)
                        continue

                    try:
                        if (
                            not isinstance(resolution, dict)
                            or resolution.get("status")
                            not in {"existing", "created"}
                        ):
                            raise MaconomyServiceError(
                                "Invalid CCH task resolution status"
                            )

                        job_number = self._required_string(
                            job.get("jobnumber"),
                            "jobnumber",
                        )
                        task_id = self._required_string(
                            resolution.get("taskid"),
                            "CCH task ID",
                        )
                        period_end_date = self._required_string(
                            job.get("periodenddate"),
                            "periodenddate",
                        )
                        source_version = self._parse_version(
                            job.get("versionnumber")
                        )
                        print("-"*50)
                        print(job_number, task_id, period_end_date, source_version)
                        saved_version = await self._update_job_task_mapping(
                            client,
                            reconnect_token,
                            job_number=job_number,
                            source_version=source_version,
                            task_id=task_id,
                            period_end_date=period_end_date,
                        )
                        updated_job["text20"] = task_id
                        updated_job["date5"] = period_end_date
                        updated_job["versionnumber"] = saved_version
                        updated_job["maconomywritebackstatus"] = "updated"
                    except Exception as exc:
                        updated_job["maconomywritebackstatus"] = "failed"
                        updated_job["maconomywritebackerror"] = (
                            self._safe_update_error_message(exc)
                        )
                    updated_jobs.append(updated_job)

                return updated_jobs
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy update request failed") from exc

    async def _update_job_task_mapping(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        *,
        job_number: str,
        source_version: int,
        task_id: str,
        period_end_date: str,
    ) -> int:
        job, instance_id, concurrency_token = await self._bind_job(
            client,
            reconnect_token,
            job_number,
        )
        current_version = self._parse_version(job.get("versionnumber"))
        if current_version != source_version:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} changed before its CCH mapping could be saved"
            )

        current_task_id = job.get("text20")
        if current_task_id is not None and (
            not isinstance(current_task_id, str) or current_task_id.strip()
        ):
            raise MaconomyServiceError(
                f"Maconomy job {job_number} already has a text20 mapping"
            )

        import datetime
        # period_end_date is expected in yyyy-mm-dd format
        period_end_date = datetime.datetime.strptime(
            period_end_date, "%m/%d/%Y"
        ).strftime("%Y-%m-%d")
        print(f"Updating Maconomy job {job_number} with task ID {task_id} and period end date {period_end_date}")
        await self._post_job_request(
            client,
            reconnect_token,
            f"/instances/{instance_id}/data/panes/card/0",
            {"data": {"text20": task_id, "date5": period_end_date}},
            concurrency_token=concurrency_token,
        )

        saved_job, _, _ = await self._bind_job(
            client,
            reconnect_token,
            job_number,
        )
        saved_version = self._parse_version(saved_job.get("versionnumber"))
        if saved_version != source_version + 1:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} version did not increase by one"
            )
        if str(saved_job.get("text20", "")).strip() != task_id:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} text20 write could not be verified"
            )
        if str(saved_job.get("date5", "")).strip() != period_end_date:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} date5 write could not be verified"
            )
        return saved_version

    async def _bind_job(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        job_number: str,
    ) -> tuple[dict[str, Any], str, str]:
        instance_response = await self._post_job_request(
            client,
            reconnect_token,
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
            instance_id_value,
            "containerInstanceId",
        )
        concurrency_token = self._response_uuid(
            instance_response.headers.get("Maconomy-Concurrency-Control"),
            "Maconomy-Concurrency-Control",
        )
        bind_response = await self._post_job_request(
            client,
            reconnect_token,
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
        client: httpx.AsyncClient,
        reconnect_token: str,
        path: str,
        payload: dict[str, Any],
        *,
        concurrency_token: str | None = None,
    ) -> httpx.Response:
        headers = self._container_headers(reconnect_token)
        if concurrency_token is not None:
            headers["Maconomy-Concurrency-Control"] = concurrency_token
        response = await client.post(
            f"{self._jobs_url()}{path}",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response

    async def _get_syncable_tax_job_records(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        *,
        today: date | None = None,
    ) -> list[dict[str, Any]]:
        current_date = today or date.today()
        start_date = current_date - timedelta(days=1)
        response = await client.post(
            f"{self._jobs_url()}/filter",
            headers=self._container_headers(reconnect_token),
            json={
                "restriction": (
                    "template=false "
                    "and closed=false "
                    "and createddate>="
                    f"date({start_date.year},{start_date.month - 1},{start_date.day}) "
                    "and createddate<="
                    f"date({current_date.year},{current_date.month},{current_date.day}) "
                    "and text20=''"
                ),
                "fields": SYNCABLE_JOB_FIELDS,
                "limit": 2000,
            },
        )
        response.raise_for_status()

        records = self._read_filter_records(response)
        return [record for record in records if self._is_syncable_tax_job(record)]

    async def _add_customer_fiscal_year_end_month(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        jobs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        specification2_names = {
            str(job["specification2name"]).strip()
            for job in jobs
            if job.get("specification2name") is not None
            and str(job["specification2name"]).strip()
        }
        specification2_records = (
            await self._get_specification2_records(client, reconnect_token)
            if specification2_names
            else []
        )
        task_types_by_specification2_name = {
            str(record["specification2name"]).strip(): str(
                record["description"]
            ).strip()
            for record in specification2_records
            if record.get("specification2name") is not None
            and str(record["specification2name"]).strip()
            and record.get("description") is not None
            and str(record["description"]).strip()
        }

        customer_numbers = list(
            dict.fromkeys(
                str(job["customernumber"])
                for job in jobs
                if job.get("customernumber") is not None and str(job["customernumber"])
            )
        )
        customers = await self._get_customer_records(
            client,
            reconnect_token,
            customer_numbers,
        )
        customers_by_number = {
            str(customer["customernumber"]): customer
            for customer in customers
            if customer.get("customernumber") is not None
        }

        enriched_jobs: list[dict[str, Any]] = []
        for job in jobs:
            enriched_job = dict(job)
            task_type = self._resolve_task_type(
                job.get("specification2name"),
                task_types_by_specification2_name,
            )
            enriched_job["tasktype"] = task_type
            if task_type is None:
                enriched_job["tasktypeerror"] = (
                    "No active Specification2 description was found for "
                    f"code {job.get('specification2name')}"
                )
            customer = customers_by_number.get(str(job.get("customernumber")))
            fiscal_year_end_month = (
                customer.get("fiscalyearendmonth") if customer is not None else None
            )
            enriched_job["fiscalyearendmonth"] = fiscal_year_end_month
            enriched_job["periodenddate"] = self._calculate_period_end_date(
                job.get("theyear"),
                fiscal_year_end_month,
            )
            enriched_jobs.append(enriched_job)

        return enriched_jobs

    @staticmethod
    def _resolve_task_type(
        specification2_name: Any,
        task_types_by_specification2_name: dict[str, str],
    ) -> str | None:
        if specification2_name is None or not str(specification2_name).strip():
            return DEFAULT_TASK_TYPE
        return task_types_by_specification2_name.get(
            str(specification2_name).strip()
        )

    async def _get_specification2_records(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> list[dict[str, Any]]:
        response = await client.post(
            f"{self._specification2_url()}/filter",
            headers=self._container_headers(reconnect_token),
            json={
                "restriction": "blocked=false",
                "fields": SPECIFICATION2_FIELDS,
                "limit": 2000,
            },
        )
        response.raise_for_status()
        return self._read_filter_records(response)

    async def _get_customer_records(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        customer_numbers: list[str],
    ) -> list[dict[str, Any]]:
        if not customer_numbers:
            return []

        restrictions: list[str] = []
        for customer_number in customer_numbers:
            escaped_customer_number = customer_number.replace("'", "''")
            restrictions.append(f"customernumber='{escaped_customer_number}'")
        response = await client.post(
            f"{self._customers_url()}/filter",
            headers=self._container_headers(reconnect_token),
            json={
                "restriction": " or ".join(restrictions),
                "fields": CUSTOMER_FIELDS,
                "limit": len(customer_numbers),
            },
        )
        response.raise_for_status()
        return self._read_filter_records(response)

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

    async def _get_reconnect_token(self, client: httpx.AsyncClient) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        credentials = (
            f"{self.settings.maconomy_username}:"
            f"{self.settings.maconomy_password.get_secret_value()}"
        )
        encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode(
            "ascii"
        )
        response = await client.get(
            f"{self.settings.maconomy_url}/maconomy-api/auth/{shortname}/login",
            headers={
                "Accept": AUTH_CONTENT_TYPE,
                "Maconomy-Authentication": "X-Reconnect",
                "Authorization": f"Basic {encoded_credentials}",
            },
        )
        response.raise_for_status()

        reconnect_token = response.headers.get("Maconomy-Reconnect", "").strip()
        if response.status_code != 204 or not reconnect_token:
            raise MaconomyServiceError("Maconomy authentication failed")
        return reconnect_token

    @staticmethod
    def _read_filter_records(response: httpx.Response) -> list[dict[str, Any]]:
        return MaconomyService._read_pane_records(response, "filter")

    @staticmethod
    def _read_pane_records(
        response: httpx.Response,
        pane_name: str,
    ) -> list[dict[str, Any]]:
        try:
            pane = response.json()["panes"][pane_name]
            raw_records = pane["records"]
            if pane["meta"]["rowCount"] == 0:
                return []
            records = [record["data"] for record in raw_records]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                f"Invalid Maconomy {pane_name} response"
            ) from exc

        if not all(isinstance(record, dict) for record in records):
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
            record.get("closed") is False
            and isinstance(location_name, str)
            and location_name.casefold() == "tax"
            and "text20" in record
            and (task_internal_id is None or task_internal_id == "")
        )

    def _jobs_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return f"{self.settings.maconomy_url}/maconomy-api/containers/{shortname}/jobs"

    def _customers_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/customercard"
        )

    def _specification2_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/specification2"
        )

    @staticmethod
    def _container_headers(reconnect_token: str) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }
