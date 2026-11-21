"""Choose one eligible job per Customer and map its enrichment properties."""

from datetime import date
from typing import Any


def _value(record: dict[str, Any], field: str) -> str:
    return str(record.get(field) or "").strip()


def _created_date(record: dict[str, Any]) -> date:
    try:
        return date.fromisoformat(_value(record, "createddate")[:10])
    except ValueError:
        return date.min


class JobCseMarketMapper:
    @staticmethod
    def select_by_customer(
        jobs: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        selected: dict[str, dict[str, Any]] = {}
        seen_jobs: set[str] = set()
        for job in jobs:
            job_number = _value(job, "jobnumber")
            customer_number = _value(job, "customernumber")
            cse = _value(job, "accountmanagername")
            market = _value(job, "specification4name")
            if (
                not job_number
                or not customer_number
                or not cse
                or not market
                or cse.lower() == "null"
                or market.lower() == "null"
                or job_number in seen_jobs
            ):
                continue
            seen_jobs.add(job_number)
            current = selected.get(customer_number)
            if current is None or _created_date(job) > _created_date(current):
                selected[customer_number] = job
        return selected

    @staticmethod
    def properties(job: dict[str, Any]) -> dict[str, str]:
        return {
            "cse": _value(job, "accountmanagername"),
            "market": _value(job, "specification4name"),
        }
