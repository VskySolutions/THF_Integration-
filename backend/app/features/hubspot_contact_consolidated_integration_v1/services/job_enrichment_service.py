"""Apply job-derived CSE and market after Company and Contact synchronization."""

from typing import Any

from app.features.hubspot_contact_consolidated_integration_v1.exceptions import (
    HubSpotError,
    MaconomyError,
)
from app.features.hubspot_contact_consolidated_integration_v1.mappers.job_cse_market_mapper import (
    JobCseMarketMapper,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.job_hubspot_service import (
    JobHubSpotService,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.maconomy_job_service import (
    MaconomyJobService,
)


def _error(
    stage: str,
    exc: MaconomyError | HubSpotError,
    customer_number: str = "",
    job_number: str = "",
) -> dict[str, Any]:
    return {
        "stage": stage,
        "reason": exc.reason,
        "customer_number": customer_number,
        "job_number": job_number,
        "upstream_status": exc.upstream_status,
        "category": getattr(exc, "category", None),
        "correlation_id": getattr(exc, "correlation_id", None),
    }


class JobEnrichmentService:
    def __init__(
        self, maconomy: MaconomyJobService, hubspot: JobHubSpotService
    ) -> None:
        self._maconomy = maconomy
        self._hubspot = hubspot

    async def run(
        self,
        customer_numbers: set[str],
        *,
        include_recent_jobs: bool,
    ) -> dict[str, Any]:
        try:
            return await self._run(customer_numbers, include_recent_jobs)
        except Exception:
            return {
                "status": "partial_success",
                "jobs_discovered": 0,
                "groups_considered": 0,
                "groups_skipped": [],
                "selected_jobs": [],
                "errors": [{
                    "stage": "job_cse_market_enrichment",
                    "reason": "unexpected_error",
                }],
            }

    async def _run(
        self, customer_numbers: set[str], include_recent_jobs: bool
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "success",
            "jobs_discovered": 0,
            "groups_considered": 0,
            "groups_skipped": [],
            "selected_jobs": [],
            "errors": [],
        }
        recent_jobs: list[dict[str, Any]] = []
        customer_jobs: list[dict[str, Any]] = []
        if include_recent_jobs:
            try:
                recent_jobs = await self._maconomy.recent_jobs()
            except MaconomyError as exc:
                result["errors"].append(_error(exc.stage, exc))
        if customer_numbers:
            try:
                customer_jobs = await self._maconomy.jobs_for_customers(
                    customer_numbers
                )
            except MaconomyError as exc:
                result["errors"].append(_error(exc.stage, exc))

        jobs = [*recent_jobs, *customer_jobs]
        result["jobs_discovered"] = len({
            str(job.get("jobnumber") or "").strip()
            for job in jobs if str(job.get("jobnumber") or "").strip()
        })
        selected = JobCseMarketMapper.select_by_customer(jobs)
        result["groups_considered"] = len(selected)
        if not selected:
            if result["errors"]:
                result["status"] = "partial_success"
            return result

        try:
            company_ids = await self._hubspot.lookup_companies(set(selected))
        except HubSpotError as exc:
            result["status"] = "partial_success"
            result["errors"].append(_error("hubspot_company_lookup", exc))
            return result

        company_properties: dict[str, dict[str, str]] = {}
        contact_properties: dict[str, dict[str, str]] = {}
        contact_owners: dict[str, str] = {}
        groups: dict[str, dict[str, Any]] = {}
        for customer_number, job in selected.items():
            job_number = str(job.get("jobnumber") or "").strip()
            company_id = company_ids.get(customer_number)
            if not company_id:
                result["groups_skipped"].append({
                    "customer_number": customer_number,
                    "job_number": job_number,
                    "reason": "company_not_in_hubspot",
                })
                continue
            properties = JobCseMarketMapper.properties(job)
            group: dict[str, Any] = {
                "customer_number": customer_number,
                "job_number": job_number,
                "job_createddate": str(job.get("createddate") or "")[:10],
                "company_id": company_id,
                "company_updated": False,
                "contacts_found": 0,
                "contacts_updated": 0,
                "contact_ids": [],
                "failed_contact_ids": [],
            }
            groups[customer_number] = group
            company_properties[company_id] = properties
            try:
                contacts = await self._hubspot.contacts_for_customer(customer_number)
            except HubSpotError as exc:
                result["errors"].append(_error(
                    "hubspot_contact_search", exc, customer_number, job_number
                ))
                continue
            for contact in contacts:
                contact_id = contact["hubspot_id"]
                contact_properties[contact_id] = properties
                contact_owners[contact_id] = customer_number
                group["contact_ids"].append(contact_id)
            group["contacts_found"] = len(group["contact_ids"])

        if company_properties:
            company_updates = await self._hubspot.update_properties_by_id(
                "company", company_properties
            )
            for customer_number, group in groups.items():
                group["company_updated"] = (
                    group["company_id"] in company_updates["confirmed_ids"]
                )
                if not group["company_updated"]:
                    context = self._context_for_id(
                        company_updates["errors"], group["company_id"]
                    )
                    result["errors"].append({
                        "stage": "hubspot_company_job_update",
                        "reason": "update_unconfirmed",
                        "customer_number": customer_number,
                        "job_number": group["job_number"],
                        **context,
                    })

        if contact_properties:
            contact_updates = await self._hubspot.update_properties_by_id(
                "contact", contact_properties
            )
            for contact_id in contact_updates["confirmed_ids"]:
                groups[contact_owners[contact_id]]["contacts_updated"] += 1
            for contact_id in contact_updates["failed_ids"]:
                customer_number = contact_owners[contact_id]
                group = groups[customer_number]
                group["failed_contact_ids"].append(contact_id)
                context = self._context_for_id(
                    contact_updates["errors"], contact_id
                )
                result["errors"].append({
                    "stage": "hubspot_contact_job_update",
                    "reason": "update_unconfirmed",
                    "customer_number": customer_number,
                    "job_number": group["job_number"],
                    "hubspot_id": contact_id,
                    **context,
                })

        result["selected_jobs"] = list(groups.values())
        if result["errors"]:
            result["status"] = "partial_success"
        return result

    @staticmethod
    def _context_for_id(
        errors: list[dict[str, Any]], hubspot_id: str
    ) -> dict[str, Any]:
        for error in errors:
            if (
                error.get("source_id") == hubspot_id
                or hubspot_id in error.get("hubspot_ids", [])
            ):
                return {
                    "category": error.get("category"),
                    "correlation_id": error.get("correlation_id"),
                    "upstream_status": error.get("upstream_status"),
                }
        return {}
