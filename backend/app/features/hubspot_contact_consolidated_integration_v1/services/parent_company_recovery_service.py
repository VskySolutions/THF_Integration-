"""Upsert Maconomy parent Customers missing as HubSpot Companies."""

from typing import Any

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


class ParentCompanyRecoveryService:
    def __init__(self, maconomy: MaconomyService, hubspot: HubSpotService) -> None:
        self.maconomy = maconomy
        self.hubspot = hubspot

    @staticmethod
    def _error(
        source_id: str,
        stage: str,
        message: str,
        exc: MaconomyError | HubSpotError | None = None,
    ) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "stage": stage,
            "message": message,
            "reason": exc.reason if exc else None,
            "upstream_status": exc.upstream_status if exc else None,
            "upstream_message": exc.upstream_message if exc else None,
            "category": exc.category if isinstance(exc, HubSpotError) else None,
            "correlation_id": (
                exc.correlation_id if isinstance(exc, HubSpotError) else None
            ),
        }

    async def run(
        self,
        customer_numbers: set[str],
        specification1_descriptions: dict[str, str],
        specification6_descriptions: dict[str, str],
    ) -> dict[str, Any]:
        confirmed_ids: dict[str, str] = {}
        errors: list[dict[str, Any]] = []
        checkpoint_errors: list[dict[str, Any]] = []
        checkpoints: list[dict[str, Any]] = []
        result: dict[str, Any] = {
            "requested": len(customer_numbers),
            "confirmed_ids": confirmed_ids,
            "checkpoints": checkpoints,
            "errors": errors,
            "checkpoint_errors": checkpoint_errors,
        }
        if not customer_numbers:
            return result

        try:
            records = await self.maconomy.get_customers_by_numbers(customer_numbers)
        except MaconomyError as exc:
            errors.extend(
                self._error(number, "parent_customer_lookup", str(exc), exc)
                for number in sorted(customer_numbers)
            )
            return result

        for number in sorted(customer_numbers - set(records)):
            errors.append(
                self._error(
                    number,
                    "parent_customer_lookup",
                    f"Parent Customer {number} was not found in Maconomy",
                )
            )
        if not records:
            return result

        spec1 = dict(specification1_descriptions)
        spec6 = dict(specification6_descriptions)
        try:
            if any(
                str(record.get("specification1name") or "").strip() not in spec1
                for record in records.values()
                if str(record.get("specification1name") or "").strip()
            ):
                spec1.update(await self.maconomy.get_specification1_descriptions())
            if any(
                str(record.get("specification6name") or "").strip() not in spec6
                for record in records.values()
                if str(record.get("specification6name") or "").strip()
            ):
                spec6.update(await self.maconomy.get_specification6_descriptions())
        except MaconomyError as exc:
            errors.extend(
                self._error(number, exc.stage, str(exc), exc)
                for number in sorted(records)
            )
            return result

        payload = CompanyMapper.build_upsert_payload(list(records.values()), spec1, spec6)
        for skipped in payload["skipped"]:
            errors.append(
                self._error(
                    str(skipped.get("source_id") or ""),
                    "parent_company_mapping",
                    str(skipped.get("reason") or "Company mapping failed"),
                )
            )
        if not payload["inputs"]:
            return result

        try:
            upsert = await self.hubspot.upsert_companies(payload["inputs"])
        except HubSpotError as exc:
            errors.extend(
                self._error(item["id"], "parent_company_upsert", str(exc), exc)
                for item in payload["inputs"]
            )
            return result

        confirmed_ids.update(upsert["confirmed_ids"])
        batch_errors = {
            item["source_id"]: item
            for item in upsert["batch_errors"]
            if item.get("source_id")
        }
        for item in payload["inputs"]:
            number = item["id"]
            if number not in confirmed_ids:
                detail = batch_errors.get(number, {})
                errors.append(
                    {
                        **self._error(
                            number,
                            "parent_company_upsert",
                            detail.get("message")
                            or f"HubSpot did not confirm parent Company {number} upsert",
                        ),
                        "category": detail.get("category"),
                        "correlation_id": detail.get("correlation_id"),
                        "details": detail.get("details", []),
                    }
                )

        for number in sorted(confirmed_ids):
            try:
                checkpoints.append(
                    await self.maconomy.update_customer_sync_version(number)
                )
            except MaconomyError as exc:
                checkpoint_errors.append(
                    self._error(number, "parent_customer_checkpoint", str(exc), exc)
                )
        return result
