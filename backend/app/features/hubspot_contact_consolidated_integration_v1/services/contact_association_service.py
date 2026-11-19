"""Add missing HubSpot Company links for created or updated contact groups."""

import asyncio
import logging
import uuid
from typing import Any

from app.features.hubspot_contact_consolidated_integration_v1.exceptions import (
    HubSpotError,
)
from app.features.hubspot_contact_consolidated_integration_v1.mappers.contact_groups import (
    ContactGroup,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.hubspot_service import (
    HubSpotService,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.maconomy_service import (
    MaconomyService,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.parent_company_recovery_service import (
    ParentCompanyRecoveryService,
)

logger = logging.getLogger(__name__)


class ContactAssociationService:
    def __init__(self, maconomy: MaconomyService, hubspot: HubSpotService) -> None:
        self.maconomy = maconomy
        self.hubspot = hubspot

    async def run(
        self,
        groups: list[ContactGroup],
        confirmed_master_ids: dict[str, str],
        confirmed_company_ids: dict[str, str],
        specification1_descriptions: dict[str, str],
        specification6_descriptions: dict[str, str],
        request_id: uuid.UUID,
    ) -> dict[str, Any]:
        candidates = [
            group
            for group in groups
            if group.master_number
            and not group.error
            and group.action in ("sync_master", "stamp_only")
        ]
        errors: list[dict[str, Any]] = []
        completed_emails: set[str] = set()
        already_present = 0
        added = 0
        pair_results: list[dict[str, str]] = []
        recovery_result: dict[str, Any] = {
            "requested": 0,
            "confirmed_ids": {},
            "checkpoints": [],
            "errors": [],
            "checkpoint_errors": [],
        }

        def failure(
            group: ContactGroup,
            stage: str,
            message: str,
            exc: HubSpotError | None = None,
            company_number: str | None = None,
        ) -> None:
            detail = {
                "email": group.email,
                "master_number": group.master_number,
                "company_number": company_number,
                "stage": stage,
                "message": message,
                "reason": exc.reason if exc else None,
                "upstream_status": exc.upstream_status if exc else None,
                "category": exc.category if exc else None,
                "correlation_id": exc.correlation_id if exc else None,
                "upstream_message": exc.upstream_message if exc else None,
            }
            errors.append(detail)
            logger.error(
                "v1 Contact association failed: request_id=%s master=%s "
                "company=%s stage=%s reason=%s upstream_status=%s category=%s",
                request_id,
                group.master_number,
                company_number,
                stage,
                detail["reason"],
                detail["upstream_status"],
                detail["category"],
            )

        if not candidates:
            return {
                "groups_considered": 0,
                "already_present": 0,
                "added": 0,
                "pair_results": pair_results,
                "completed_emails": completed_emails,
                "parent_company_recovery": recovery_result,
                "errors": errors,
            }

        master_ids = dict(confirmed_master_ids)
        missing_masters = {
            group.master_number
            for group in candidates
            if group.action == "stamp_only" and group.master_number not in master_ids
        }
        if missing_masters:
            try:
                master_ids.update(await self.hubspot.lookup_contacts(missing_masters))
            except HubSpotError as exc:
                for group in candidates:
                    if group.master_number in missing_masters:
                        failure(group, "hubspot_contact_lookup", str(exc), exc)

        ready: list[ContactGroup] = []
        for group in candidates:
            if not group.parent_companies():
                failure(
                    group,
                    "maconomy_parent_companies",
                    "No Company number is present in the full Maconomy contact group",
                )
            elif group.action == "sync_master" and group.master_number not in confirmed_master_ids:
                failure(
                    group,
                    "hubspot_contact_upsert",
                    "HubSpot did not confirm the MASTER Contact upsert",
                )
            elif group.master_number not in master_ids and not any(
                error["email"] == group.email for error in errors
            ):
                failure(
                    group,
                    "hubspot_contact_lookup",
                    "MASTER Contact was not found in HubSpot",
                )
            elif group.master_number in master_ids:
                ready.append(group)

        company_ids = dict(confirmed_company_ids)
        missing_companies = (
            set().union(*(group.parent_companies() for group in ready)) - set(company_ids)
            if ready
            else set()
        )
        if missing_companies:
            try:
                company_ids.update(await self.hubspot.lookup_companies(missing_companies))
            except HubSpotError as exc:
                for group in ready:
                    if group.parent_companies() & missing_companies:
                        failure(group, "hubspot_company_lookup", str(exc), exc)
                ready = [
                    group
                    for group in ready
                    if not group.parent_companies() & missing_companies
                ]

        still_missing = (
            set().union(*(group.parent_companies() for group in ready)) - set(company_ids)
            if ready
            else set()
        )
        if still_missing:
            recovery_result = await ParentCompanyRecoveryService(
                self.maconomy, self.hubspot
            ).run(
                still_missing,
                specification1_descriptions,
                specification6_descriptions,
            )
            company_ids.update(recovery_result["confirmed_ids"])
            errors.extend(
                {"email": None, **error}
                for error in recovery_result["checkpoint_errors"]
            )

        recovery_errors = {
            error["source_id"]: error for error in recovery_result["errors"]
        }

        for group in ready:
            for number in sorted(group.parent_companies()):
                if number not in company_ids:
                    issue = recovery_errors.get(number, {})
                    errors.append(
                        {
                            "email": group.email,
                            "master_number": group.master_number,
                            "company_number": number,
                            "stage": issue.get("stage") or "parent_company_recovery",
                            "message": issue.get("message")
                            or f"Parent Company {number} could not be created in HubSpot",
                            "reason": issue.get("reason"),
                            "upstream_status": issue.get("upstream_status"),
                            "upstream_message": issue.get("upstream_message"),
                            "category": issue.get("category"),
                            "correlation_id": issue.get("correlation_id"),
                            "details": issue.get("details", []),
                        }
                    )

        resolvable = [
            group for group in ready
            if not any(error["email"] == group.email for error in errors)
        ]
        existing: dict[str, set[str]] = {}
        if resolvable:
            try:
                existing = await self.hubspot.read_contact_company_associations(
                    {master_ids[group.master_number] for group in resolvable}
                )
            except HubSpotError as exc:
                for group in resolvable:
                    failure(group, "hubspot_association_lookup", str(exc), exc)
                resolvable = []

        semaphore = asyncio.Semaphore(10)

        async def add_missing(group: ContactGroup, company_number: str) -> bool:
            contact_id = master_ids[group.master_number]
            company_id = company_ids[company_number]
            try:
                async with semaphore:
                    await self.hubspot.associate_contact_to_company(contact_id, company_id)
                return True
            except HubSpotError as exc:
                failure(group, "hubspot_association_create", str(exc), exc, company_number)
                return False

        tasks: list[tuple[ContactGroup, str]] = []
        for group in resolvable:
            contact_id = master_ids[group.master_number]
            for company_number in sorted(group.parent_companies()):
                if company_ids[company_number] in existing.get(contact_id, set()):
                    already_present += 1
                    pair_results.append({
                        "master_number": group.master_number,
                        "company_number": company_number,
                        "status": "already_present",
                    })
                else:
                    tasks.append((group, company_number))
        if tasks:
            results = await asyncio.gather(
                *(add_missing(group, number) for group, number in tasks)
            )
            added = sum(results)
            pair_results.extend(
                {
                    "master_number": group.master_number,
                    "company_number": number,
                    "status": "added" if succeeded else "failed",
                }
                for (group, number), succeeded in zip(tasks, results)
            )

        completed_emails = {
            group.email
            for group in resolvable
            if not any(error["email"] == group.email for error in errors)
        }
        return {
            "groups_considered": len(candidates),
            "already_present": already_present,
            "added": added,
            "pair_results": pair_results,
            "completed_emails": completed_emails,
            "parent_company_recovery": {
                "requested": recovery_result["requested"],
                "confirmed_ids": recovery_result["confirmed_ids"],
                "checkpoints": recovery_result["checkpoints"],
                "errors": recovery_result["errors"],
                "checkpoint_errors": recovery_result["checkpoint_errors"],
            },
            "errors": errors,
        }
