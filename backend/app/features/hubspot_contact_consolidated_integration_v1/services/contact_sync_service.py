"""Resolve master contacts, upsert masters, and stamp empty child remark4 fields."""

import logging
import uuid
from typing import Any

from app.features.hubspot_contact_consolidated_integration_v1.exceptions import (
    HubSpotError,
    MaconomyError,
)
from app.features.hubspot_contact_consolidated_integration_v1.mappers.contact_groups import (
    ContactConsolidator,
)
from app.features.hubspot_contact_consolidated_integration_v1.mappers.contact_mapper import (
    ContactMapper,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.hubspot_service import (
    HubSpotService,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.maconomy_service import (
    MaconomyService,
)

logger = logging.getLogger(__name__)


def _maconomy_error(exc: MaconomyError) -> dict[str, Any]:
    return {
        "stage": exc.stage,
        "reason": exc.reason,
        "upstream_status": exc.upstream_status,
        "message": str(exc),
        "upstream_message": exc.upstream_message,
    }


class ContactSyncService:
    def __init__(self, maconomy: MaconomyService, hubspot: HubSpotService) -> None:
        self.maconomy = maconomy
        self.hubspot = hubspot

    async def run(
        self,
        classified_contacts: dict[str, list[dict[str, Any]]],
        new_customer_numbers: list[str],
        request_id: uuid.UUID,
    ) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        contacts = [
            *classified_contacts["new_contact_persons"],
            *classified_contacts["updated_contact_persons"],
        ]
        if new_customer_numbers:
            try:
                contacts.extend(
                    await self.maconomy.get_contacts_for_customers(
                        new_customer_numbers
                    )
                )
            except MaconomyError as exc:
                logger.exception(
                    "v1 contacts of new customers lookup failed: request_id=%s "
                    "stage=%s reason=%s upstream_status=%s upstream_message=%s",
                    request_id,
                    exc.stage,
                    exc.reason,
                    exc.upstream_status,
                    exc.upstream_message,
                )
                errors.append({"stage": "new_customer_contacts_lookup", **_maconomy_error(exc)})

        consolidator = ContactConsolidator()
        deduplicated = consolidator.deduplicate(contacts)
        selected = self.maconomy.classify_contact_persons(deduplicated)
        changed_contacts = [
            *selected["new_contact_persons"],
            *selected["updated_contact_persons"],
        ]
        selected["skipped"].extend(
            {
                "source_id": str(item.get("contactpersonnumber") or "").strip(),
                "reason": "missing electronicmailaddress",
            }
            for item in changed_contacts
            if not str(item.get("electronicmailaddress") or "").strip()
        )
        changed_numbers = {
            str(item.get("contactpersonnumber") or "").strip()
            for item in changed_contacts
        }
        groups = consolidator.group_contacts(changed_contacts)
        back_query_emails = [group.email for group in groups]
        back_query: dict[str, list[dict[str, Any]]] = {}
        back_query_failed = False
        if back_query_emails:
            try:
                back_query = await self.maconomy.get_contact_persons_by_emails(
                    back_query_emails
                )
            except MaconomyError as exc:
                back_query_failed = True
                logger.exception(
                    "v1 master contact back-query failed: request_id=%s "
                    "stage=%s reason=%s upstream_status=%s upstream_message=%s",
                    request_id,
                    exc.stage,
                    exc.reason,
                    exc.upstream_status,
                    exc.upstream_message,
                )
                errors.append(_maconomy_error(exc))

        for group in groups:
            needs_back_query = group.email in back_query_emails
            if needs_back_query and back_query_failed:
                group.error = "full email group lookup failed; master not elected"
            else:
                consolidator.resolve(
                    group,
                    changed_numbers,
                    back_query.get(group.email, []) if needs_back_query else None,
                )
            if group.error:
                errors.append(
                    {
                        "stage": "master_resolution",
                        "email": group.email,
                        "message": group.error,
                    }
                )

        sync_groups = [group for group in groups if group.action == "sync_master"]
        payload = ContactMapper.build_upsert_payload(
            [group.master_record for group in sync_groups if group.master_record]
        )
        errors.extend(
            {"stage": "contact_mapping", **item} for item in payload["skipped"]
        )
        upsert_result: dict[str, Any] = {
            "requested": len(payload["inputs"]),
            "confirmed_ids": {},
            "batch_errors": [],
        }
        if payload["inputs"]:
            try:
                upsert_result = await self.hubspot.upsert_contacts(payload["inputs"])
            except HubSpotError as exc:
                logger.exception(
                    "v1 master Contact upsert failed: request_id=%s reason=%s "
                    "upstream_status=%s batch=%s category=%s correlation_id=%s "
                    "upstream_message=%s",
                    request_id,
                    exc.reason,
                    exc.upstream_status,
                    exc.batch_number,
                    exc.category,
                    exc.correlation_id,
                    exc.upstream_message,
                )
                errors.append(
                    {
                        "stage": "hubspot_contact_upsert",
                        "reason": exc.reason,
                        "upstream_status": exc.upstream_status,
                        "batch_number": exc.batch_number,
                        "category": exc.category,
                        "correlation_id": exc.correlation_id,
                        "message": str(exc),
                        "upstream_message": exc.upstream_message,
                    }
                )

        confirmed_ids: dict[str, str] = upsert_result["confirmed_ids"]
        errors_by_source = {
            item["source_id"]: item
            for item in upsert_result["batch_errors"]
            if item["source_id"]
        }
        for item in payload["inputs"]:
            if item["id"] not in confirmed_ids:
                detail = errors_by_source.get(item["id"], {})
                errors.append(
                    {
                        "stage": "hubspot_contact_upsert",
                        "source_id": item["id"],
                        "message": detail.get("message")
                        or "HubSpot did not confirm the master Contact upsert",
                        "category": detail.get("category"),
                        "details": detail.get("details", []),
                        "correlation_id": detail.get("correlation_id"),
                    }
                )

        stampable = [
            group
            for group in groups
            if group.action == "stamp_only"
            or (
                group.action == "sync_master"
                and group.master_number in confirmed_ids
            )
        ]
        stamps: list[dict[str, Any]] = []
        for group in stampable:
            for child in group.unstamped_children():
                child_number = str(child.get("contactpersonnumber") or "").strip()
                try:
                    stamp = await self.maconomy.write_contact_master_stamp(
                        child_number, group.master_number or ""
                    )
                    stamps.append(stamp)
                except MaconomyError as exc:
                    logger.exception(
                        "v1 Contact master stamp failed: request_id=%s "
                        "source_id=%s master=%s stage=%s reason=%s "
                        "upstream_status=%s upstream_message=%s",
                        request_id,
                        child_number,
                        group.master_number,
                        exc.stage,
                        exc.reason,
                        exc.upstream_status,
                        exc.upstream_message,
                    )
                    errors.append(
                        {
                            "source_id": child_number,
                            "master_number": group.master_number,
                            **_maconomy_error(exc),
                        }
                    )

        if errors or selected["skipped"] or upsert_result["batch_errors"]:
            logger.warning(
                "v1 Contact sync was partial: request_id=%s groups=%s "
                "masters_requested=%s masters_confirmed=%s children_stamped=%s "
                "errors=%s skipped=%s batch_errors=%s",
                request_id,
                len(groups),
                upsert_result["requested"],
                len(confirmed_ids),
                len([stamp for stamp in stamps if stamp["written"]]),
                errors,
                selected["skipped"],
                upsert_result["batch_errors"],
            )

        return {
            "groups": [group.summary() for group in groups],
            "masters_requested": upsert_result["requested"],
            "masters_upserted": len(confirmed_ids),
            "master_contact_ids": confirmed_ids,
            "batch_errors": upsert_result["batch_errors"],
            "children_stamped": len([stamp for stamp in stamps if stamp["written"]]),
            "stamps": stamps,
            "skipped": selected["skipped"],
            "errors": errors,
        }
