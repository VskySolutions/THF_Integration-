"""Sync Companies, then resolve and sync master Contacts."""

import logging
import uuid
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.hubspot_contact_consolidated_integration_v1.exceptions import (
    HubSpotError,
    MaconomyError,
)
from app.features.hubspot_contact_consolidated_integration_v1.mappers.company_mapper import (
    CompanyMapper,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.contact_sync_service import (
    ContactSyncService,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.hubspot_service import (
    HubSpotService,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.integration_run_log_service import (
    V1ConsolidationRunLogger,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.maconomy_service import (
    MaconomyService,
)

logger = logging.getLogger(__name__)


class ConsolidatedSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._run_logger = V1ConsolidationRunLogger(session)
        self._stage = "run_start"
        self._progress: dict[str, int] = {
            "customers_discovered": 0,
            "customers_succeeded": 0,
            "contacts_discovered": 0,
            "contacts_succeeded": 0,
            "associations_succeeded": 0,
            "checkpoints_succeeded": 0,
        }

    async def run_bulk(
        self,
        request_id: uuid.UUID,
        trigger_type: str,
    ) -> dict[str, Any]:
        await self._run_logger.start(
            request_id, trigger_type, get_settings().maconomy_shortname
        )
        try:
            result = await self._run_bulk(request_id, trigger_type)
        except Exception as exc:
            await self._run_logger.fail(
                self._stage, exc.__cause__ or exc, self._progress
            )
            raise
        await self._run_logger.complete(result)
        return result

    async def _run_bulk(
        self,
        request_id: uuid.UUID,
        trigger_type: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            maconomy = MaconomyService(client)
            try:
                self._stage = "maconomy_authentication"
                await maconomy.authenticate()
                self._stage = "customer_discovery"
                customers = await maconomy.discover_customers()
                classified = maconomy.classify_customers(customers)
                selected_customers = [
                    *classified["new_customers"],
                    *classified["updated_customers"],
                ]
                self._progress["customers_discovered"] = len(selected_customers)
                self._stage = "specification_lookup"
                specification1_descriptions = (
                    await maconomy.get_specification1_descriptions()
                    if any(
                        str(customer.get("specification1name") or "").strip()
                        for customer in selected_customers
                    )
                    else {}
                )
                specification6_descriptions = (
                    await maconomy.get_specification6_descriptions()
                    if any(
                        str(customer.get("specification6name") or "").strip()
                        for customer in selected_customers
                    )
                    else {}
                )
            except MaconomyError as exc:
                logger.error(
                    "v1 Maconomy bulk read failed: request_id=%s stage=%s "
                    "reason=%s upstream_status=%s",
                    request_id,
                    exc.stage,
                    exc.reason,
                    exc.upstream_status,
                )
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            self._stage = "company_mapping"
            company_payload = CompanyMapper.build_upsert_payload(
                selected_customers,
                specification1_descriptions,
                specification6_descriptions,
            )
            try:
                self._stage = "hubspot_company_upsert"
                upsert_result = await HubSpotService(client).upsert_companies(
                    company_payload["inputs"]
                )
            except HubSpotError as exc:
                logger.error(
                    "v1 HubSpot Company upsert failed: request_id=%s "
                    "reason=%s upstream_status=%s batch=%s category=%s "
                    "correlation_id=%s",
                    request_id,
                    exc.reason,
                    exc.upstream_status,
                    exc.batch_number,
                    exc.category,
                    exc.correlation_id,
                )
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            confirmed_ids = upsert_result["confirmed_ids"]
            checkpoints_written: list[dict[str, Any]] = []
            writeback_errors: list[dict[str, Any]] = []
            self._stage = "maconomy_customer_writeback"
            for source_id in confirmed_ids:
                try:
                    checkpoint = await maconomy.update_customer_sync_version(source_id)
                    checkpoints_written.append(checkpoint)
                except MaconomyError as exc:
                    logger.error(
                        "v1 Maconomy customer writeback failed: request_id=%s "
                        "source_id=%s stage=%s reason=%s upstream_status=%s",
                        request_id,
                        source_id,
                        exc.stage,
                        exc.reason,
                        exc.upstream_status,
                    )
                    writeback_errors.append(
                        {
                            "source_id": source_id,
                            "stage": exc.stage,
                            "reason": exc.reason,
                            "upstream_status": exc.upstream_status,
                            "message": str(exc),
                            "upstream_message": exc.upstream_message,
                        }
                    )
            self._progress["checkpoints_succeeded"] = len(checkpoints_written)
            self._progress["customers_succeeded"] = len(checkpoints_written)

            contact_discovery_error: dict[str, Any] | None = None
            try:
                self._stage = "contact_discovery"
                contact_records = await maconomy.discover_contact_persons()
                classified_contacts = maconomy.classify_contact_persons(
                    contact_records
                )
                self._progress["contacts_discovered"] = (
                    len(classified_contacts["new_contact_persons"])
                    + len(classified_contacts["updated_contact_persons"])
                )
            except MaconomyError as exc:
                logger.error(
                    "v1 Maconomy contact discovery failed: request_id=%s "
                    "stage=%s reason=%s upstream_status=%s",
                    request_id,
                    exc.stage,
                    exc.reason,
                    exc.upstream_status,
                )
                contact_records = []
                classified_contacts = {
                    "new_contact_persons": [],
                    "updated_contact_persons": [],
                    "skipped": [],
                }
                contact_discovery_error = {
                    "stage": exc.stage,
                    "reason": exc.reason,
                    "upstream_status": exc.upstream_status,
                    "message": str(exc),
                    "upstream_message": exc.upstream_message,
                }

            self._stage = "contact_sync"
            contact_sync_result = await ContactSyncService(
                maconomy, HubSpotService(client)
            ).run(
                classified_contacts,
                [
                    str(customer.get("customernumber") or "").strip()
                    for customer in classified["new_customers"]
                    if str(customer.get("customernumber") or "").strip()
                ],
                request_id,
                confirmed_ids,
                specification1_descriptions,
                specification6_descriptions,
            )

        errors_by_source = {
            error["source_id"]: error
            for error in upsert_result["batch_errors"]
            if error["source_id"]
        }
        failed_customers = []
        for item in company_payload["inputs"]:
            source_id = item["id"]
            if source_id in confirmed_ids:
                continue
            error = errors_by_source.get(source_id, {})
            failed_customers.append(
                {
                    "source_id": source_id,
                    "reason": "HubSpot did not confirm the Company upsert",
                    "category": error.get("category"),
                    "sub_category": error.get("sub_category"),
                    "correlation_id": error.get("correlation_id"),
                    "message": error.get("message"),
                    "details": error.get("details", []),
                }
            )

        if failed_customers or upsert_result["batch_errors"] or writeback_errors:
            logger.warning(
                "v1 Company sync was partial: request_id=%s "
                "requested=%s confirmed=%s hubspot_failed=%s "
                "writeback_failed=%s batch_errors=%s",
                request_id,
                upsert_result["requested"],
                len(confirmed_ids),
                len(failed_customers),
                len(writeback_errors),
                len(upsert_result["batch_errors"]),
            )
        if classified_contacts["skipped"]:
            logger.warning(
                "v1 Maconomy contact discovery skipped records: request_id=%s "
                "count=%s",
                request_id,
                len(classified_contacts["skipped"]),
            )

        return {
            "status": (
                "partial_success"
                if (
                    failed_customers
                    or company_payload["skipped"]
                    or upsert_result["batch_errors"]
                    or writeback_errors
                    or contact_discovery_error
                    or classified_contacts["skipped"]
                    or contact_sync_result["skipped"]
                    or contact_sync_result["errors"]
                    or contact_sync_result["batch_errors"]
                )
                else "success"
            ),
            "new_customers": classified["new_customers"],
            "updated_customers": classified["updated_customers"],
            "hubspot": {
                "companies_requested": upsert_result["requested"],
                "companies_upserted": len(confirmed_ids),
                "company_ids": confirmed_ids,
                "failed_customers": failed_customers,
                "batch_errors": upsert_result["batch_errors"],
            },
            "maconomy": {
                "checkpoints_requested": len(confirmed_ids),
                "checkpoints_written": len(checkpoints_written),
                "checkpoints": checkpoints_written,
                "writeback_errors": writeback_errors,
            },
            "contact_persons": {
                "discovered": len(contact_records),
                "new_contact_persons": classified_contacts["new_contact_persons"],
                "updated_contact_persons": classified_contacts[
                    "updated_contact_persons"
                ],
                "skipped": [
                    *classified_contacts["skipped"],
                    *contact_sync_result["skipped"],
                ],
                "discovery_error": contact_discovery_error,
                **{
                    key: value
                    for key, value in contact_sync_result.items()
                    if key != "skipped"
                },
            },
            "skipped": company_payload["skipped"],
        }
