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

SYNCABLE_JOB_FIELDS = [
    "jobnumber",
    "locationname",
    "customernumber",
    "theyear",
    "text20",
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
                    f"date({start_date.year},{start_date.month - 5},{start_date.day}) "
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
        try:
            filter_pane = response.json()["panes"]["filter"]
            raw_records = filter_pane["records"]
            if filter_pane["meta"]["rowCount"] == 0:
                return []
            records = [record["data"] for record in raw_records]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy job response") from exc

        if not all(isinstance(record, dict) for record in records):
            raise MaconomyServiceError("Invalid Maconomy job response")
        return records

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

    @staticmethod
    def _container_headers(reconnect_token: str) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }
