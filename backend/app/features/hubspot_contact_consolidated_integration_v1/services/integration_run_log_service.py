"""Persist ID-only v1 run outcomes in the shared HubSpot run-log table."""

import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.hubspot_contact_consolidated_integration.models import (
    ConsolidationRunLog,
)

logger = logging.getLogger(__name__)
_IDENTIFIER = re.compile(r"[0-9]{1,30}\Z")
_CODE = re.compile(r"[A-Za-z0-9_:-]{1,100}\Z")
_SKIP_REASONS = {
    "missing or empty customernumber": "missing_customer_number",
    "duplicate customernumber in discovery result": "duplicate_customer_number",
    "missing contactpersonnumber": "missing_contact_number",
    "duplicate contactpersonnumber": "duplicate_contact_number",
    "invalid versionnumber": "invalid_version_number",
    "invalid remark5": "invalid_sync_version",
    "remark5 exceeds versionnumber": "sync_version_exceeds_version",
    "missing electronicmailaddress": "missing_email",
    "missing contactpersonnumber or email": "missing_contact_number_or_email",
    "duplicate master contact number": "duplicate_master_number",
}


def _id(value: Any) -> str:
    text = str(value or "").strip()
    return text if _IDENTIFIER.fullmatch(text) else ""


def _code(value: Any, default: str = "unknown") -> str:
    text = str(value or "").strip()
    return text if _CODE.fullmatch(text) else default


def _ids(records: list[dict[str, Any]], field: str) -> set[str]:
    return {number for item in records if (number := _id(item.get(field)))}


def _safe_error(item: dict[str, Any], entity_type: str) -> dict[str, Any]:
    stage = _code(item.get("stage"))
    reason = _code(item.get("reason"), "failed")
    source_id = _id(item.get("source_id")) or (
        _id(item.get("company_number"))
        if entity_type == "customer"
        else _id(item.get("master_number"))
    )
    result: dict[str, Any] = {
        "entity_type": entity_type,
        "source_id": source_id,
        "stage": stage,
        "reason": reason,
        "message": f"{stage.replace('_', ' ')}: {reason.replace('_', ' ')}",
    }
    parent_number = _id(item.get("company_number")) if entity_type == "contact" else ""
    if parent_number:
        result["parent_customer_number"] = parent_number
    status = item.get("upstream_status")
    if isinstance(status, int) and 100 <= status <= 599:
        result["upstream_status"] = status
    for field in ("category", "correlation_id"):
        value = _code(item.get(field), "")
        if value:
            result[field] = value
    raw_details = item.get("details")
    property_names = {
        name
        for detail in (raw_details if isinstance(raw_details, list) else [])[:10]
        if isinstance(detail, dict)
        for name in (
            _code(value, "")
            for value in (
                detail.get("property_names")
                if isinstance(detail.get("property_names"), list)
                else []
            )
        )
        if name
    }
    if property_names:
        result["property_names"] = sorted(property_names)
    return result


def _safe_skip(item: dict[str, Any], entity_type: str) -> dict[str, str]:
    raw_reason = str(item.get("reason") or "").strip()
    return {
        "entity_type": entity_type,
        "source_id": _id(item.get("source_id")),
        "reason": _SKIP_REASONS.get(raw_reason, _code(raw_reason, "skipped")),
        "message": "Record skipped during selection or mapping",
    }


def _run_details(result: dict[str, Any]) -> dict[str, Any]:
    contacts = result["contact_persons"]
    hubspot = result["hubspot"]
    maconomy = result["maconomy"]
    associations = contacts["associations"]
    recovery = associations["parent_company_recovery"]

    main_customer_ids = _ids(
        [*result["new_customers"], *result["updated_customers"]],
        "customernumber",
    )
    selected_contact_ids = {
        number for value in contacts["selected_contact_numbers"]
        if (number := _id(value))
    }
    company_ids = {
        number
        for value in [*hubspot["company_ids"], *recovery["confirmed_ids"]]
        if (number := _id(value))
    }
    customer_checkpoints = _ids(maconomy["checkpoints"], "source_id") | _ids(
        recovery["checkpoints"], "source_id"
    )
    contact_checkpoints = _ids(contacts["checkpoints"], "source_id")
    customer_attempts = main_customer_ids | {
        number for value in recovery["confirmed_ids"] if (number := _id(value))
    } | {
        number
        for item in recovery["errors"]
        if (number := _id(item.get("source_id")))
    }

    errors: list[dict[str, Any]] = []
    errors.extend(
        _safe_error({
            "stage": "hubspot_company_upsert",
            **item,
            "reason": "upsert_unconfirmed",
        }, "customer")
        for item in hubspot["failed_customers"]
    )
    errors.extend(
        _safe_error(item, "customer") for item in maconomy["writeback_errors"]
    )
    errors.extend(
        _safe_error({"stage": "hubspot_company_upsert", **item}, "customer")
        for item in hubspot["batch_errors"]
        if not _id(item.get("source_id"))
    )
    if contacts.get("discovery_error"):
        errors.append(_safe_error(contacts["discovery_error"], "contact"))
    for item in contacts["errors"]:
        stage = _code(item.get("stage"))
        entity_type = (
            "customer"
            if stage.startswith("parent_customer")
            or stage.startswith("parent_company")
            or stage == "hubspot_company_lookup"
            else "contact"
        )
        errors.append(_safe_error(item, entity_type))
    errors.extend(
        _safe_error({"stage": "hubspot_contact_upsert", **item}, "contact")
        for item in contacts["batch_errors"]
        if not _id(item.get("source_id"))
    )
    unique_errors = list({
        (item["entity_type"], item["source_id"], item["stage"],
         item.get("parent_customer_number", "")): item
        for item in errors
    }.values())

    skipped = [
        *(_safe_skip(item, "customer") for item in result["skipped"]),
        *(_safe_skip(item, "contact") for item in contacts["skipped"]),
    ]
    skipped = list({
        (item["entity_type"], item["source_id"], item["reason"]): item
        for item in skipped
    }.values())
    failure_by_record = {
        (item["entity_type"], item["source_id"]): item
        for item in unique_errors if item["source_id"]
    }
    skip_by_record = {
        (item["entity_type"], item["source_id"]): item
        for item in skipped if item["source_id"]
    }
    record_results: list[dict[str, Any]] = []
    pending_records: list[dict[str, Any]] = []
    for entity_type, numbers, succeeded in (
        ("customer", customer_attempts, customer_checkpoints & company_ids),
        ("contact", selected_contact_ids, contact_checkpoints),
    ):
        for number in sorted(numbers):
            key = (entity_type, number)
            if key in failure_by_record:
                record_results.append({**failure_by_record[key], "status": "FAILED"})
            elif key in skip_by_record:
                record_results.append({**skip_by_record[key], "status": "SKIPPED"})
            elif number in succeeded:
                record_results.append({
                    "entity_type": entity_type, "source_id": number,
                    "status": "SUCCESS", "stage": "checkpoint_complete",
                    "message": "HubSpot sync and Maconomy checkpoint confirmed",
                })
            else:
                pending = {
                    "entity_type": entity_type, "source_id": number,
                    "status": "FAILED", "stage": "checkpoint_pending",
                    "message": "Sync or checkpoint was not confirmed",
                }
                record_results.append(pending)
                pending_records.append(pending)

    pairs = [
        {
            "master_number": _id(item.get("master_number")),
            "company_number": _id(item.get("company_number")),
            "status": _code(item.get("status")),
        }
        for item in associations["pair_results"]
        if _id(item.get("master_number")) and _id(item.get("company_number"))
    ]
    stamps = contacts["stamps"]
    groups = [
        {
            "master_contact_person_number": master,
            "action": _code(group.get("action")),
            "member_numbers": sorted(
                number for value in group.get("member_numbers", [])
                if (number := _id(value))
            ),
            "parent_customer_numbers": sorted(
                number for value in group.get("parent_customer_numbers", [])
                if (number := _id(value))
            ),
            "members": sum(
                bool(_id(value)) for value in group.get("member_numbers", [])
            ),
            "upserted": master in contacts["master_contact_ids"],
            "stamped_members": sum(
                item.get("master_number") == master and item.get("written")
                for item in stamps
            ),
            "checkpointed_members": sum(
                item.get("master_number") == master
                for item in contacts["checkpoints"]
            ),
            "associations_added": sum(
                item["master_number"] == master and item["status"] == "added"
                for item in pairs
            ),
            "associations_existing": sum(
                item["master_number"] == master and item["status"] == "already_present"
                for item in pairs
            ),
        }
        for group in contacts["groups"]
        for master in [_id(group.get("master_contact_person_number"))]
    ]

    failure_stages = Counter(
        item["stage"] for item in [*unique_errors, *pending_records]
    )
    failed_records = [
        *[item for item in unique_errors if item["source_id"]],
        *pending_records,
    ]
    run_errors = [item for item in unique_errors if not item["source_id"]]
    failed_keys = {
        (item["entity_type"], item["source_id"])
        for item in failed_records
    }
    counts = {
        "customers_discovered": len(customer_attempts),
        "customers_succeeded": len(customer_checkpoints & company_ids),
        "contacts_discovered": len(selected_contact_ids),
        "contacts_succeeded": len(selected_contact_ids & contact_checkpoints),
        "masters_upserted": contacts["masters_upserted"],
        "children_stamped": contacts["children_stamped"],
        "companies_recovered": len(recovery["confirmed_ids"]),
        "associations_succeeded": associations["added"],
        "associations_existing": associations["already_present"],
        "checkpoints_succeeded": len(customer_checkpoints) + len(contact_checkpoints),
        "skipped": len(skipped),
        "failed": len(failed_keys) + len(run_errors),
    }
    return {
        "version": "v1",
        "counts": counts,
        "failure_stage_counts": dict(failure_stages),
        "failed_records": failed_records,
        "skipped_records": skipped,
        "record_results": record_results,
        "group_summaries": groups,
        "association_pairs": pairs,
        "run_errors": run_errors,
    }


class V1ConsolidationRunLogger:
    """Keep one durable row per v1 bulk execution."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._row: ConsolidationRunLog | None = None

    async def start(self, request_id: uuid.UUID, trigger_type: str, instance: str) -> None:
        self._row = ConsolidationRunLog(
            request_id=request_id,
            operation="CONSOLIDATED_BULK_SYNC_V1",
            trigger_type=trigger_type,
            status="RUNNING",
            maconomy_instance=instance,
            summary_message="v1 HubSpot sync is running",
            details={"version": "v1"},
        )
        self._session.add(self._row)
        if not await self._commit():
            self._row = None

    async def complete(self, result: dict[str, Any]) -> None:
        if self._row is None:
            return
        try:
            details = _run_details(result)
        except Exception:
            logger.exception("v1 HubSpot run-log summary could not be prepared")
            details = {
                "version": "v1",
                "counts": {
                    "customers_discovered": 0,
                    "customers_succeeded": 0,
                    "contacts_discovered": 0,
                    "contacts_succeeded": 0,
                    "associations_succeeded": 0,
                    "checkpoints_succeeded": 0,
                    "skipped": 0,
                    "failed": 1,
                },
                "failure_stage_counts": {"run_log_summary": 1},
                "failed_records": [],
                "skipped_records": [],
                "record_results": [],
                "group_summaries": [],
                "association_pairs": [],
                "run_errors": [_safe_error(
                    {"stage": "run_log_summary", "reason": "summary_failed"}, "run"
                )],
            }
        counts = details["counts"]
        row = self._row
        row.status = (
            "PARTIAL_SUCCESS"
            if result["status"] == "partial_success" or counts["failed"] or counts["skipped"]
            else "SUCCESS"
        )
        row.completed_on_utc = datetime.now(timezone.utc)
        row.customers_discovered = counts["customers_discovered"]
        row.customers_succeeded = counts["customers_succeeded"]
        row.contacts_discovered = counts["contacts_discovered"]
        row.contacts_succeeded = counts["contacts_succeeded"]
        row.associations_succeeded = counts["associations_succeeded"]
        row.checkpoints_succeeded = counts["checkpoints_succeeded"]
        row.skipped_count = counts["skipped"]
        row.failed_count = counts["failed"]
        row.summary_message = (
            f"Companies {row.customers_succeeded}/{row.customers_discovered}; "
            f"Contacts {row.contacts_succeeded}/{row.contacts_discovered}; "
            f"links added {row.associations_succeeded}; "
            f"failed {row.failed_count}"
        )
        row.failure_stage = (
            ",".join(sorted(details["failure_stage_counts"])) or None
        )
        row.error_message = (
            "One or more v1 sync stages need attention"
            if row.failed_count or row.skipped_count
            else None
        )
        row.details = details
        await self._commit()

    async def fail(
        self,
        stage: str,
        cause: BaseException | None = None,
        progress: dict[str, int] | None = None,
    ) -> None:
        if self._row is None:
            return
        row = self._row
        safe_stage = _code(stage, "bulk_execution")
        reason = _code(getattr(cause, "reason", None), "failed")
        counts = {
            key: max(0, int((progress or {}).get(key, 0)))
            for key in (
                "customers_discovered",
                "customers_succeeded",
                "contacts_discovered",
                "contacts_succeeded",
                "associations_succeeded",
                "checkpoints_succeeded",
            )
        }
        counts["failed"] = 1
        row.status = "FAILED"
        row.completed_on_utc = datetime.now(timezone.utc)
        row.customers_discovered = counts["customers_discovered"]
        row.customers_succeeded = counts["customers_succeeded"]
        row.contacts_discovered = counts["contacts_discovered"]
        row.contacts_succeeded = counts["contacts_succeeded"]
        row.associations_succeeded = counts["associations_succeeded"]
        row.checkpoints_succeeded = counts["checkpoints_succeeded"]
        row.failed_count = 1
        row.failure_stage = safe_stage
        row.error_message = f"{safe_stage.replace('_', ' ')}: {reason.replace('_', ' ')}"
        row.summary_message = f"v1 HubSpot sync failed during {safe_stage.replace('_', ' ')}"
        row.details = {
            "version": "v1",
            "counts": counts,
            "failure_stage_counts": {safe_stage: 1},
            "failed_records": [],
            "skipped_records": [],
            "record_results": [],
            "group_summaries": [],
            "association_pairs": [],
            "run_errors": [_safe_error({
                "stage": safe_stage,
                "reason": reason,
                "upstream_status": getattr(cause, "upstream_status", None),
                "category": getattr(cause, "category", None),
                "correlation_id": getattr(cause, "correlation_id", None),
            }, "run")],
        }
        await self._commit()

    async def _commit(self) -> bool:
        try:
            await self._session.commit()
            return True
        except Exception:
            await self._session.rollback()
            logger.exception("v1 HubSpot run-log database write failed")
            return False
