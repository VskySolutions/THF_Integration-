"""Retry one Company and the Contact Persons attached to that Customer."""

import re
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


class CompanyRetryService:
    """Execute the manual Company path independently from bulk discovery."""

    def __init__(self, session: AsyncSession) -> None:
        self._run_logger = V1ConsolidationRunLogger(session)
        self._stage = "company_retry_start"
        self._progress = {
            "customers_discovered": 0,
            "customers_succeeded": 0,
            "contacts_discovered": 0,
            "contacts_succeeded": 0,
            "associations_succeeded": 0,
            "checkpoints_succeeded": 0,
        }

    async def run(self, request_id: uuid.UUID, customer_number: str) -> dict[str, Any]:
        number = customer_number.strip()
        if not re.fullmatch(r"(?=.*[0-9])[A-Za-z0-9_-]{1,30}", number):
            raise HTTPException(status_code=422, detail="Enter a valid Customer number")

        await self._run_logger.start(
            request_id,
            "MANUAL",
            get_settings().maconomy_shortname,
            operation="CONSOLIDATED_COMPANY_RETRY_V1",
        )
        try:
            result = await self._run_customer(request_id, number)
        except (MaconomyError, HubSpotError) as exc:
            await self._run_logger.fail(
                self._stage, exc, self._progress, source_id=number
            )
            http_status = (
                404 if isinstance(exc, MaconomyError) and exc.reason == "customer_not_found"
                else 502
            )
            raise HTTPException(status_code=http_status, detail=str(exc)) from exc
        except Exception as exc:
            await self._run_logger.fail(
                self._stage, exc, self._progress, source_id=number
            )
            raise

        await self._run_logger.complete(result)
        contacts = result["contact_persons"]
        return {
            "status": result["status"],
            "request_id": str(request_id),
            "customer_number": number,
            "company_upserted": bool(result["hubspot"]["company_ids"]),
            "company_checkpoint_written": bool(result["maconomy"]["checkpoints"]),
            "contacts_considered": len(contacts["selected_contact_numbers"]),
            "masters_upserted": contacts["masters_upserted"],
            "associations_added": contacts["associations"]["added"],
            "associations_existing": contacts["associations"]["already_present"],
            "contact_checkpoints_written": contacts["checkpoints_written"],
        }

    async def _run_customer(
        self, request_id: uuid.UUID, number: str
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            maconomy = MaconomyService(client)
            hubspot = HubSpotService(client)

            self._stage = "maconomy_authentication"
            await maconomy.authenticate()
            self._stage = "customer_lookup"
            customer = (await maconomy.get_customers_by_numbers({number})).get(number)
            if customer is None:
                raise MaconomyError(
                    f"Maconomy Customer {number} was not found",
                    stage="customer_lookup",
                    reason="customer_not_found",
                )
            self._progress["customers_discovered"] = 1

            self._stage = "specification_lookup"
            specification1 = (
                await maconomy.get_specification1_descriptions()
                if str(customer.get("specification1name") or "").strip()
                else {}
            )
            specification6 = (
                await maconomy.get_specification6_descriptions()
                if str(customer.get("specification6name") or "").strip()
                else {}
            )

            self._stage = "company_mapping"
            payload = CompanyMapper.build_upsert_payload(
                [customer], specification1, specification6
            )
            if not payload["inputs"]:
                raise MaconomyError(
                    f"Maconomy Customer {number} cannot be mapped to a Company",
                    stage="company_mapping",
                    reason="mapping_failed",
                )

            self._stage = "hubspot_company_upsert"
            company_upsert = await hubspot.upsert_companies(payload["inputs"])
            company_ids = company_upsert["confirmed_ids"]
            if number not in company_ids:
                batch_error = next(
                    (
                        item for item in company_upsert["batch_errors"]
                        if item.get("source_id") == number
                    ),
                    {},
                )
                return {
                    "status": "partial_success",
                    "new_customers": [customer] if not str(customer.get("customerremark26") or "").strip() else [],
                    "updated_customers": [customer] if str(customer.get("customerremark26") or "").strip() else [],
                    "hubspot": {
                        "companies_requested": 1,
                        "companies_upserted": 0,
                        "company_ids": {},
                        "failed_customers": [{
                            "source_id": number,
                            "category": batch_error.get("category"),
                            "correlation_id": batch_error.get("correlation_id"),
                            "details": batch_error.get("details", []),
                        }],
                        "batch_errors": company_upsert["batch_errors"],
                    },
                    "maconomy": {
                        "checkpoints_requested": 0,
                        "checkpoints_written": 0,
                        "checkpoints": [],
                        "writeback_errors": [],
                    },
                    "contact_persons": {
                        "discovered": 0,
                        "new_contact_persons": [],
                        "updated_contact_persons": [],
                        "skipped": [],
                        "discovery_error": None,
                        "groups": [],
                        "selected_contact_numbers": [],
                        "masters_upserted": 0,
                        "master_contact_ids": {},
                        "associations": {
                            "added": 0,
                            "already_present": 0,
                            "pair_results": [],
                            "parent_company_recovery": {
                                "confirmed_ids": {},
                                "checkpoints": [],
                                "errors": [],
                            },
                        },
                        "batch_errors": [],
                        "children_stamped": 0,
                        "stamps": [],
                        "checkpoints_written": 0,
                        "checkpoints": [],
                        "errors": [],
                    },
                    "skipped": [],
                }

            self._stage = "company_contacts_lookup"
            contact_records = [
                item
                for item in await maconomy.get_contacts_for_customers([number])
                if str(item.get("contactcompanynumber") or "").strip() == number
            ]
            if len(contact_records) >= 5000:
                raise MaconomyError(
                    f"Maconomy Customer {number} has reached the Contact lookup limit",
                    stage="company_contacts_lookup",
                    reason="contact_limit_reached",
                )
            self._progress["contacts_discovered"] = len(contact_records)

            self._stage = "contact_sync"
            contact_result = await ContactSyncService(maconomy, hubspot).run(
                {
                    "new_contact_persons": contact_records,
                    "updated_contact_persons": [],
                    "skipped": [],
                },
                [],
                request_id,
                company_ids,
                specification1,
                specification6,
                company_scope_number=number,
            )
            self._progress["contacts_discovered"] = len(
                contact_result["selected_contact_numbers"]
            )
            self._progress["associations_succeeded"] = contact_result[
                "associations"
            ]["added"]
            self._progress["contacts_succeeded"] = contact_result[
                "checkpoints_written"
            ]
            self._progress["checkpoints_succeeded"] = contact_result[
                "checkpoints_written"
            ]

            self._stage = "maconomy_customer_writeback"
            company_checkpoints: list[dict[str, Any]] = []
            writeback_errors: list[dict[str, Any]] = []
            try:
                company_checkpoints.append(
                    await maconomy.update_customer_sync_version(number)
                )
                self._progress["customers_succeeded"] = 1
                self._progress["checkpoints_succeeded"] += 1
            except MaconomyError as exc:
                writeback_errors.append({
                    "source_id": number,
                    "stage": exc.stage,
                    "reason": exc.reason,
                    "upstream_status": exc.upstream_status,
                })

        partial = bool(
            contact_result["errors"]
            or contact_result["skipped"]
            or contact_result["batch_errors"]
            or company_upsert["batch_errors"]
            or writeback_errors
        )
        return {
            "status": "partial_success" if partial else "success",
            "new_customers": [customer] if not str(customer.get("customerremark26") or "").strip() else [],
            "updated_customers": [customer] if str(customer.get("customerremark26") or "").strip() else [],
            "hubspot": {
                "companies_requested": 1,
                "companies_upserted": 1,
                "company_ids": company_ids,
                "failed_customers": [],
                "batch_errors": company_upsert["batch_errors"],
            },
            "maconomy": {
                "checkpoints_requested": 1,
                "checkpoints_written": len(company_checkpoints),
                "checkpoints": company_checkpoints,
                "writeback_errors": writeback_errors,
            },
            "contact_persons": {
                "discovered": len(contact_records),
                "new_contact_persons": [],
                "updated_contact_persons": [],
                "discovery_error": None,
                **contact_result,
            },
            "skipped": [],
        }
