"""Read eligible Maconomy jobs for the CSE and market extension phase."""

from datetime import date, timedelta
from typing import Any

from app.features.hubspot_contact_consolidated_integration_v1.constants import (
    JOB_CSE_MARKET_FIELDS,
    SYNC_WINDOW_DAYS,
)
from app.features.hubspot_contact_consolidated_integration_v1.exceptions import (
    MaconomyError,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.maconomy_service import (
    MaconomyService,
)

JOB_PAGE_SIZE = 500
MAX_JOB_RECORDS = 100000
ELIGIBLE_JOBS = (
    "closed=false and template=false "
    "and accountmanagername!='null' and specification4name!='null' "
    "and accountmanagername!='' and specification4name!=''"
)


class MaconomyJobService:
    def __init__(self, maconomy: MaconomyService) -> None:
        self._maconomy = maconomy

    async def recent_jobs(self) -> list[dict[str, Any]]:
        start = date.today() - timedelta(days=SYNC_WINDOW_DAYS)
        end = date.today() + timedelta(days=1)
        window_start = f"date({start.year},{start.month},{start.day})"
        window_end = f"date({end.year},{end.month},{end.day})"
        return await self._read_all(
            f"{ELIGIBLE_JOBS} and "
            f"((createddate>={window_start} and createddate<{window_end}) "
            f"or (changeddate>={window_start} and changeddate<{window_end}))",
            "job_discovery",
        )

    async def jobs_for_customers(
        self, customer_numbers: set[str]
    ) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        numbers = sorted(number for number in customer_numbers if number)
        for offset in range(0, len(numbers), 25):
            chunk = numbers[offset : offset + 25]
            restriction = " or ".join(
                f"customernumber='{number.replace(chr(39), chr(39) * 2)}'"
                for number in chunk
            )
            jobs.extend(await self._read_all(
                f"{ELIGIBLE_JOBS} and ({restriction})",
                "customer_job_lookup",
            ))
        return jobs

    async def _read_all(self, restriction: str, stage: str) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        offset = 0
        prior_page: tuple[str, str] | None = None
        while True:
            page = await self._maconomy._filter_records(
                container="jobs",
                restriction=restriction,
                fields=JOB_CSE_MARKET_FIELDS,
                limit=JOB_PAGE_SIZE,
                offset=offset,
                stage=stage,
            )
            if not page:
                break
            fingerprint = (
                str(page[0].get("jobnumber") or ""),
                str(page[-1].get("jobnumber") or ""),
            )
            if offset and fingerprint == prior_page:
                raise MaconomyError(
                    "Maconomy jobs filter repeated a page",
                    stage=stage,
                    reason="pagination_failed",
                )
            jobs.extend(page)
            if len(jobs) > MAX_JOB_RECORDS:
                raise MaconomyError(
                    "Maconomy jobs filter exceeded the supported page limit",
                    stage=stage,
                    reason="job_limit_reached",
                )
            if len(page) < JOB_PAGE_SIZE:
                break
            prior_page = fingerprint
            offset += len(page)
        return jobs
