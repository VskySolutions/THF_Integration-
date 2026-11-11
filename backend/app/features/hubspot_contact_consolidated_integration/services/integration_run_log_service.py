import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.hubspot_contact_consolidated_integration.models import (
    ConsolidationRunLog,
)


def sanitize_record_references(
    records: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Keep only source identifiers and safe operational context in logs."""
    sanitized: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for record in records or []:
        source_id = str(record.get("source_id") or "").strip()
        if not source_id:
            continue
        entity_type = str(record.get("entity_type") or "record").strip()
        stage = str(record.get("stage") or "").strip()
        reason = str(record.get("reason") or "").strip()
        key = (entity_type, source_id, stage, reason)
        if key in seen:
            continue
        seen.add(key)

        item = {
            "entity_type": entity_type,
            "source_id": source_id,
        }
        for field in (
            "parent_customer_number",
            "stage",
            "reason",
            "message",
        ):
            value = str(record.get(field) or "").strip()
            if value:
                item[field] = value
        sanitized.append(item)

    return sanitized


def record_result_ledger(
    *,
    successful_records: list[dict[str, Any]] | None,
    failed_records: list[dict[str, Any]] | None,
    skipped_records: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Build one final status row per Customer or Contact Person number."""
    ledger: dict[tuple[str, str], dict[str, str]] = {}

    for status, records in (
        ("SUCCESS", successful_records),
        ("SKIPPED", skipped_records),
        ("FAILED", failed_records),
    ):
        for record in sanitize_record_references(records):
            item = {**record, "status": status}
            ledger[(item["entity_type"], item["source_id"])] = item

    entity_order = {"customer": 0, "contact": 1}
    return sorted(
        ledger.values(),
        key=lambda item: (
            entity_order.get(item["entity_type"], 2),
            item["source_id"],
        ),
    )


def sanitize_group_summaries(
    summaries: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Keep operational group counts without persisting email addresses."""
    sanitized: list[dict[str, Any]] = []
    for summary in summaries or []:
        master_number = str(
            summary.get("master_contact_person_number")
            or summary.get("master")
            or ""
        ).strip()
        if not master_number:
            continue
        sanitized.append(
            {
                "master_contact_person_number": master_number,
                "action": str(summary.get("action") or "unknown"),
                "members": int(summary.get("members") or 0),
                "upserted": bool(summary.get("upserted")),
                "stamped_members": int(summary.get("stamped_members") or 0),
            }
        )
    return sanitized


class ConsolidationRunLogger:
    """DB logger for one consolidated Maconomy-to-HubSpot run."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._run_log: ConsolidationRunLog | None = None

    @property
    def run_log(self) -> ConsolidationRunLog | None:
        return self._run_log

    async def start_run(
        self,
        *,
        request_id: uuid.UUID,
        maconomy_instance: str,
        operation: str,
        trigger_type: str,
    ) -> bool:
        run_log = ConsolidationRunLog(
            request_id=request_id,
            operation=operation,
            trigger_type=trigger_type,
            status="RUNNING",
            maconomy_instance=maconomy_instance,
            summary_message="Consolidated HubSpot integration run is in progress",
        )
        try:
            self._session.add(run_log)
            await self._session.commit()
            await self._session.refresh(run_log)
        except Exception:
            await self._session.rollback()
            self._run_log = None
            return False
        self._run_log = run_log
        return True

    async def complete_run(
        self,
        *,
        status: str,
        customers_discovered: int = 0,
        customers_succeeded: int = 0,
        contacts_discovered: int = 0,
        contacts_succeeded: int = 0,
        associations_succeeded: int = 0,
        checkpoints_succeeded: int = 0,
        skipped_count: int = 0,
        errors: list[dict[str, Any]] | None = None,
        skipped_records: list[dict[str, Any]] | None = None,
        successful_records: list[dict[str, Any]] | None = None,
        group_summaries: list[dict[str, Any]] | None = None,
    ) -> bool:
        run_log = self._run_log
        if run_log is None:
            return False

        errors = errors or []
        normalized_status = (
            "PARTIAL_SUCCESS" if status == "partial_success" else "SUCCESS"
        )
        error_stages = Counter(
            str(error.get("stage") or "UNKNOWN") for error in errors
        )
        failed_count = len(errors)
        skipped_records = skipped_records or []
        successful_records = successful_records or []

        run_log.status = normalized_status
        run_log.completed_on_utc = datetime.now(timezone.utc)
        run_log.customers_discovered = customers_discovered
        run_log.customers_succeeded = customers_succeeded
        run_log.contacts_discovered = contacts_discovered
        run_log.contacts_succeeded = contacts_succeeded
        run_log.associations_succeeded = associations_succeeded
        run_log.checkpoints_succeeded = checkpoints_succeeded
        run_log.skipped_count = skipped_count
        run_log.failed_count = failed_count
        run_log.summary_message = (
            f"Customers: {customers_succeeded}/{customers_discovered} succeeded; "
            f"Contacts: {contacts_succeeded}/{contacts_discovered} succeeded; "
            f"Associations: {associations_succeeded}; "
            f"Checkpoints: {checkpoints_succeeded}; "
            f"Skipped: {skipped_count}; Failed: {failed_count}"
        )
        run_log.failure_stage = (
            ",".join(sorted(error_stages)) if error_stages else None
        )
        run_log.error_message = (
            "One or more synchronization stages failed" if errors else None
        )
        sanitized_failed_records = sanitize_record_references(errors)
        sanitized_skipped_records = sanitize_record_references(skipped_records)
        run_log.details = {
            "counts": {
                "customers_discovered": customers_discovered,
                "customers_succeeded": customers_succeeded,
                "contacts_discovered": contacts_discovered,
                "contacts_succeeded": contacts_succeeded,
                "associations_succeeded": associations_succeeded,
                "checkpoints_succeeded": checkpoints_succeeded,
                "skipped": skipped_count,
                "failed": failed_count,
            },
            "failure_stage_counts": dict(error_stages),
            "failed_records": sanitized_failed_records,
            "skipped_records": sanitized_skipped_records,
            "record_results": record_result_ledger(
                successful_records=successful_records,
                failed_records=sanitized_failed_records,
                skipped_records=sanitized_skipped_records,
            ),
            "group_summaries": sanitize_group_summaries(group_summaries),
        }
        return await self._commit()

    async def fail_run(
        self,
        *,
        failure_stage: str,
        error_message: str,
        customers_discovered: int = 0,
        contacts_discovered: int = 0,
        failed_records: list[dict[str, Any]] | None = None,
        successful_records: list[dict[str, Any]] | None = None,
    ) -> bool:
        run_log = self._run_log
        if run_log is None:
            return False

        contextual_failed_records = [
            {
                **record,
                "stage": record.get("stage") or failure_stage,
                "message": record.get("message") or error_message,
            }
            for record in failed_records or []
        ]
        sanitized_failed_records = sanitize_record_references(
            contextual_failed_records
        )
        record_results = record_result_ledger(
            successful_records=successful_records,
            failed_records=sanitized_failed_records,
            skipped_records=None,
        )
        successful_customers = sum(
            item["entity_type"] == "customer" and item["status"] == "SUCCESS"
            for item in record_results
        )
        successful_contacts = sum(
            item["entity_type"] == "contact" and item["status"] == "SUCCESS"
            for item in record_results
        )
        failed_count = max(1, len(sanitized_failed_records))
        run_log.status = "FAILED"
        run_log.completed_on_utc = datetime.now(timezone.utc)
        run_log.customers_discovered = customers_discovered
        run_log.customers_succeeded = successful_customers
        run_log.contacts_discovered = contacts_discovered
        run_log.contacts_succeeded = successful_contacts
        run_log.associations_succeeded = successful_contacts
        run_log.checkpoints_succeeded = successful_customers + successful_contacts
        run_log.failed_count = failed_count
        run_log.summary_message = (
            f"Consolidated HubSpot integration failed during {failure_stage}"
        )
        run_log.failure_stage = failure_stage
        run_log.error_message = error_message
        run_log.details = {
            "counts": {
                "customers_discovered": customers_discovered,
                "customers_succeeded": successful_customers,
                "contacts_discovered": contacts_discovered,
                "contacts_succeeded": successful_contacts,
                "associations_succeeded": successful_contacts,
                "checkpoints_succeeded": (
                    successful_customers + successful_contacts
                ),
                "failed": failed_count,
            },
            "failure_stage_counts": {failure_stage: failed_count},
            "failed_records": sanitized_failed_records,
            "skipped_records": [],
            "record_results": record_results,
        }
        return await self._commit()

    async def _commit(self) -> bool:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            return False
        return True
