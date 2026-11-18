"""Discover Maconomy customers and upsert them as HubSpot Companies."""

import logging
import uuid
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.hubspot_contact_consolidated_integration_v1.exceptions import (
    HubSpotError,
    MaconomyError,
)
from app.features.hubspot_contact_consolidated_integration_v1.mappers.company_mapper import (
    CompanyMapper,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.hubspot_service import (
    HubSpotService,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.maconomy_service import (
    MaconomyService,
)

logger = logging.getLogger(__name__)


class ConsolidatedSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run_bulk(
        self,
        request_id: uuid.UUID,
        trigger_type: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            maconomy = MaconomyService(client)
            try:
                await maconomy.authenticate()
                customers = await maconomy.discover_customers()
                classified = maconomy.classify_customers(customers)
                selected_customers = [
                    *classified["new_customers"],
                    *classified["updated_customers"],
                ]
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
                logger.exception(
                    "v1 Maconomy bulk read failed: request_id=%s stage=%s "
                    "reason=%s upstream_status=%s",
                    request_id,
                    exc.stage,
                    exc.reason,
                    exc.upstream_status,
                )
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            company_payload = CompanyMapper.build_upsert_payload(
                selected_customers,
                specification1_descriptions,
                specification6_descriptions,
            )
            try:
                upsert_result = await HubSpotService(client).upsert_companies(
                    company_payload["inputs"]
                )
            except HubSpotError as exc:
                logger.exception(
                    "v1 HubSpot Company upsert failed: request_id=%s "
                    "reason=%s upstream_status=%s batch=%s category=%s "
                    "correlation_id=%s upstream_message=%s",
                    request_id,
                    exc.reason,
                    exc.upstream_status,
                    exc.batch_number,
                    exc.category,
                    exc.correlation_id,
                    exc.upstream_message,
                )
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            confirmed_ids = upsert_result["confirmed_ids"]
            checkpoints_written: list[dict[str, Any]] = []
            writeback_errors: list[dict[str, Any]] = []
            for source_id in confirmed_ids:
                try:
                    checkpoint = await maconomy.update_customer_sync_version(source_id)
                    checkpoints_written.append(checkpoint)
                except MaconomyError as exc:
                    logger.exception(
                        "v1 Maconomy customer writeback failed: request_id=%s "
                        "source_id=%s stage=%s reason=%s upstream_status=%s "
                        "upstream_message=%s",
                        request_id,
                        source_id,
                        exc.stage,
                        exc.reason,
                        exc.upstream_status,
                        exc.upstream_message,
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
                "writeback_failed=%s batch_errors=%s writeback_errors=%s",
                request_id,
                upsert_result["requested"],
                len(confirmed_ids),
                len(failed_customers),
                len(writeback_errors),
                upsert_result["batch_errors"],
                writeback_errors,
            )

        return {
            "status": (
                "partial_success"
                if (
                    failed_customers
                    or company_payload["skipped"]
                    or upsert_result["batch_errors"]
                    or writeback_errors
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
            "skipped": company_payload["skipped"],
        }
