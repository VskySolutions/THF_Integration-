import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.hubspot_contact_consolidated_integration.constants import (
    CONTACT_COMPANY_NUMBER_FIELD,
    CONTACT_PERSON_NUMBER_FIELD,
    CUSTOMER_NUMBER_FIELD,
    EMAIL_FIELD,
    MID_RUN_BACK_QUERY_CONCURRENCY,
)
from app.features.hubspot_contact_consolidated_integration.exceptions import (
    HubSpotError,
    MaconomyError,
    MaconomyRecordNotFoundError,
)
from app.features.hubspot_contact_consolidated_integration.mappers.company_mapper import (
    CompanyMapper,
)
from app.features.hubspot_contact_consolidated_integration.mappers.contact_groups import (
    ContactConsolidator,
    ContactGroup,
)
from app.features.hubspot_contact_consolidated_integration.mappers.contact_mapper import (
    ContactMapper,
)
from app.features.hubspot_contact_consolidated_integration.services.hubspot_service import (
    HubSpotService,
)
from app.features.hubspot_contact_consolidated_integration.services.integration_run_log_service import (
    ConsolidationRunLogger,
)
from app.features.hubspot_contact_consolidated_integration.services.maconomy_service import (
    MaconomyService,
)


@dataclass
class _RunLedger:
    errors: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    successful: list[dict[str, Any]] = field(default_factory=list)
    customers_discovered: int = 0
    customers_succeeded: int = 0
    contacts_discovered: int = 0
    contacts_succeeded: int = 0
    associations_succeeded: int = 0
    checkpoints_succeeded: int = 0

    def add_error(self, item: dict[str, Any]) -> None:
        self.errors.append(item)

    def add_skip(self, item: dict[str, Any]) -> None:
        self.skipped.append(item)

    def add_success(self, item: dict[str, Any]) -> None:
        self.successful.append(item)


class _BranchFailure(Exception):
    """Fatal error raised by one parallel branch."""

    def __init__(
        self,
        *,
        stage: str,
        message: str,
        customers_discovered: int,
        contacts_discovered: int,
        failed_records: list[dict[str, Any]],
        cause: str = "",
    ) -> None:
        self.stage = stage
        self.message = message
        self.cause = cause
        self.customers_discovered = customers_discovered
        self.contacts_discovered = contacts_discovered
        self.failed_records = failed_records
        super().__init__(message)


@dataclass
class _ContactBranchState:
    contact_ids: dict[str, str] = field(default_factory=dict)
    groups: list[ContactGroup] = field(default_factory=list)
    group_summaries: list[dict[str, Any]] = field(default_factory=list)
    stamped_numbers: set[str] = field(default_factory=set)
    checkpointed_masters: set[str] = field(default_factory=set)


class ConsolidatedSyncService:
    """Orchestrates the consolidated Maconomy-to-HubSpot synchronization."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._logger = ConsolidationRunLogger(session)

    async def run_bulk(
        self,
        request_id: uuid.UUID,
        trigger_type: str,
    ) -> dict[str, Any]:
        run_started = await self._logger.start_run(
            request_id=request_id,
            maconomy_instance=get_settings().maconomy_shortname,
            operation="CONSOLIDATED_BULK_SYNC",
            trigger_type=trigger_type,
        )
        ledger = _RunLedger()

        async with httpx.AsyncClient(timeout=60.0) as client:
            maconomy = MaconomyService(client)
            hubspot = HubSpotService(client)

            try:
                customer_records, contact_records = await asyncio.gather(
                    maconomy.discover_customers(),
                    maconomy.discover_contact_persons(),
                )
            except MaconomyError as exc:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="MACONOMY_DISCOVERY",
                        error_message=str(exc) or "Unable to discover changes",
                    )
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Unable to retrieve customers and contacts from Maconomy"
                    ),
                ) from exc
            customers = maconomy.classify_customers(customer_records)
            contacts = maconomy.classify_contact_persons(contact_records)
            ledger.skipped.extend([*customers["skipped"], *contacts["skipped"]])

            all_customers = [
                *customers["new_customers"],
                *customers["updated_customers"],
            ]
            customers_by_id = {
                str(customer.get(CUSTOMER_NUMBER_FIELD) or "").strip(): customer
                for customer in all_customers
                if str(customer.get(CUSTOMER_NUMBER_FIELD) or "").strip()
            }
            ledger.customers_discovered = len(customers_by_id)

            new_customer_numbers = {
                str(customer.get(CUSTOMER_NUMBER_FIELD) or "").strip()
                for customer in customers["new_customers"]
            }
            try:
                contacts_of_new_customers = (
                    maconomy.get_contacts_for_customers(
                        sorted(new_customer_numbers)
                    )
                    if new_customer_numbers
                    else []
                )
            except MaconomyError as exc:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="MACONOMY_CONTACT_LOOKUP",
                        error_message=str(exc),
                        customers_discovered=ledger.customers_discovered,
                        contacts_discovered=len(contacts["changed_contacts"]),
                        failed_records=[
                            {
                                "entity_type": "contact",
                                "source_id": None,
                                "reason": (
                                    "complete contact list fetch failed for "
                                    f"new customer {number}"
                                ),
                            }
                            for number in sorted(new_customer_numbers)
                        ],
                    )
                raise HTTPException(
                    status_code=502,
                    detail="Unable to retrieve contacts of new customers",
                ) from exc

            consolidator = ContactConsolidator()
            deduplicated_contacts = consolidator.deduplicate(
                [*contacts["changed_contacts"], *contacts_of_new_customers]
            )
            final_contacts = maconomy.classify_contact_persons(
                deduplicated_contacts
            )
            ledger.skipped.extend(final_contacts["skipped"])
            changed_contacts = final_contacts["changed_contacts"]
            changed_numbers = {
                str(contact.get(CONTACT_PERSON_NUMBER_FIELD) or "").strip()
                for contact in changed_contacts
            }
            ledger.contacts_discovered = len(changed_numbers)

            for contact in changed_contacts:
                if not str(contact.get(EMAIL_FIELD) or "").strip():
                    ledger.add_skip(
                        {
                            "entity_type": "contact",
                            "source_id": str(
                                contact.get(CONTACT_PERSON_NUMBER_FIELD) or ""
                            ).strip(),
                            "reason": "missing or empty electronicmailaddress",
                        }
                    )

            email_groups = consolidator.group_contacts(changed_contacts)
            groups = [
                consolidator.build_group(
                    email=email,
                    members=members,
                    changed_numbers=changed_numbers,
                )
                for email, members in email_groups.items()
            ]
            groups = await self._resolve_groups_with_back_query(
                maconomy,
                groups,
                changed_numbers,
                ledger,
            )

            company_branch = self._run_company_branch(
                hubspot,
                maconomy,
                all_customers,
                customers_by_id,
                ledger,
            )
            contact_branch = self._run_contact_branch(
                maconomy,
                hubspot,
                consolidator,
                groups,
                customers_by_id,
                ledger,
            )
            try:
                company_state, contact_state = await asyncio.gather(
                    company_branch,
                    contact_branch,
                )
            except _BranchFailure as exc:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage=exc.stage,
                        error_message=exc.message,
                        customers_discovered=exc.customers_discovered,
                        contacts_discovered=exc.contacts_discovered,
                        failed_records=exc.failed_records,
                        successful_records=ledger.successful,
                    )
                raise HTTPException(
                    status_code=502,
                    detail=exc.message,
                ) from exc

            company_ids: dict[str, str] = company_state["company_ids"]
            association_pairs = await self._run_association_phase(
                maconomy,
                hubspot,
                groups,
                company_ids,
                contact_state,
                ledger,
            )

            status = "partial_success" if ledger.errors else "success"
            result = self._bulk_result(
                status,
                ledger,
                company_ids,
                contact_state,
                groups,
                association_pairs,
            )
            if run_started:
                await self._logger.complete_run(
                    status=status,
                    customers_discovered=ledger.customers_discovered,
                    customers_succeeded=ledger.customers_succeeded,
                    contacts_discovered=ledger.contacts_discovered,
                    contacts_succeeded=ledger.contacts_succeeded,
                    associations_succeeded=ledger.associations_succeeded,
                    checkpoints_succeeded=ledger.checkpoints_succeeded,
                    skipped_count=len(ledger.skipped),
                    errors=ledger.errors,
                    skipped_records=ledger.skipped,
                    successful_records=ledger.successful,
                    group_summaries=contact_state.group_summaries,
                )
            return result

    async def run_company_manual(
        self,
        request_id: uuid.UUID,
        customer_number: str,
    ) -> dict[str, Any]:
        run_started = await self._logger.start_run(
            request_id=request_id,
            maconomy_instance=get_settings().maconomy_shortname,
            operation="CONSOLIDATED_CUSTOMER_RETRY",
            trigger_type="MANUAL",
        )
        normalized_customer_number = customer_number.strip()
        if not normalized_customer_number:
            raise HTTPException(
                status_code=422,
                detail="customer_number is required",
            )
        ledger = _RunLedger()
        ledger.customers_discovered = 1
        print("9",normalized_customer_number)
        async with httpx.AsyncClient(timeout=60.0) as client:
            maconomy = MaconomyService(client)
            hubspot = HubSpotService(client)

            try:
                customer = await maconomy.get_customer_with_contacts(
                    normalized_customer_number
                )
            except MaconomyRecordNotFoundError as exc:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="MACONOMY_CUSTOMER_LOOKUP",
                        error_message="Requested Customer was not found",
                        failed_records=self._customer_records(
                            normalized_customer_number
                        ),
                    )
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except MaconomyError as exc:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="MACONOMY_CUSTOMER_LOOKUP",
                        error_message=(
                            "1 Unable to retrieve the Customer from Maconomy"
                        ),
                        failed_records=self._customer_records(
                            normalized_customer_number
                        ),
                    )
                raise HTTPException(
                    status_code=502,
                    detail="1 Unable to retrieve the Customer from Maconomy",
                ) from exc

            company_payload = CompanyMapper().build_upsert_payload([customer])
            print(company_payload)
            if not company_payload["inputs"]:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="COMPANY_MAPPING",
                        error_message="Customer could not be mapped for HubSpot",
                        customers_discovered=1,
                        failed_records=self._customer_records(
                            normalized_customer_number,
                            "company_mapping",
                        ),
                    )
                raise HTTPException(
                    status_code=422,
                    detail="Customer cannot be mapped for HubSpot",
                )

            try:
                company_result = await hubspot.upsert_companies(company_payload)
            except HubSpotError as exc:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="HUBSPOT_COMPANY_UPSERT",
                        error_message=(
                            "Unable to synchronize the Company with HubSpot"
                        ),
                        customers_discovered=1,
                        failed_records=self._customer_records(
                            normalized_customer_number,
                            "hubspot_company_upsert",
                        ),
                    )
                raise HTTPException(
                    status_code=502,
                    detail="Unable to synchronize the Company with HubSpot",
                ) from exc

            company_ids = hubspot.index_results_by_source_id(
                company_result,
                trace_prefix="company-",
                property_name="maconomy_customer_number",
            )
            company_id = company_ids.get(normalized_customer_number)
            if not company_id:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="HUBSPOT_COMPANY_UPSERT",
                        error_message="HubSpot did not confirm the Company upsert",
                        customers_discovered=1,
                        failed_records=self._customer_records(
                            normalized_customer_number,
                            "hubspot_company_upsert",
                        ),
                    )
                raise HTTPException(
                    status_code=502,
                    detail="HubSpot did not confirm the Company upsert",
                )

            checkpoint_written = False
            try:
                await maconomy.update_customer_sync_version(
                    normalized_customer_number
                )
                checkpoint_written = True
                ledger.checkpoints_succeeded += 1
                ledger.customers_succeeded = 1
                ledger.add_success(
                    {
                        "entity_type": "customer",
                        "source_id": normalized_customer_number,
                        "stage": "completed",
                        "message": (
                            "Company upsert and Maconomy write-back succeeded"
                        ),
                    }
                )
            except MaconomyError as exc:
                ledger.add_error(
                    {
                        "entity_type": "customer",
                        "source_id": normalized_customer_number,
                        "stage": "maconomy_checkpoint",
                        "message": str(exc),
                    }
                )

            errors = ledger.errors
            if run_started:
                await self._logger.complete_run(
                    status="partial_success" if errors else "success",
                    customers_discovered=1,
                    customers_succeeded=ledger.customers_succeeded,
                    checkpoints_succeeded=ledger.checkpoints_succeeded,
                    skipped_count=0,
                    errors=errors,
                    skipped_records=ledger.skipped,
                    successful_records=ledger.successful,
                )
            return {
                "status": "partial_success" if errors else "success",
                "customer": {
                    "source_id": normalized_customer_number,
                    "hubspot_id": company_id,
                    "hubspot_upserted": True,
                    "checkpoint_written": checkpoint_written,
                },
                "errors": errors,
            }

    async def run_contact_manual(
        self,
        request_id: uuid.UUID,
        contact_person_number: str,
    ) -> dict[str, Any]:
        run_started = await self._logger.start_run(
            request_id=request_id,
            maconomy_instance=get_settings().maconomy_shortname,
            operation="CONSOLIDATED_CONTACT_RETRY",
            trigger_type="MANUAL",
        )
        normalized_contact_number = contact_person_number.strip()
        if not normalized_contact_number:
            if run_started:
                await self._logger.fail_run(
                    failure_stage="CONTACT_VALIDATION",
                    error_message="contact_person_number is required",
                    contacts_discovered=1,
                    failed_records=self._contact_records(
                        normalized_contact_number, None, "contact_validation"
                    ),
                )
            raise HTTPException(
                status_code=422,
                detail="contact_person_number is required",
            )
        ledger = _RunLedger()
        ledger.contacts_discovered = 1

        async with httpx.AsyncClient(timeout=60.0) as client:
            maconomy = MaconomyService(client)
            hubspot = HubSpotService(client)

            try:
                contact: dict[str, Any] = await maconomy.get_contact_person(
                    normalized_contact_number
                )
            except MaconomyRecordNotFoundError as exc:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="MACONOMY_CONTACT_LOOKUP",
                        error_message="Requested Contact Person was not found",
                        contacts_discovered=1,
                        failed_records=self._contact_records(
                            normalized_contact_number, None, "maconomy_contact_lookup"
                        ),
                    )
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except MaconomyError as exc:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="MACONOMY_CONTACT_LOOKUP",
                        error_message=(
                            "Unable to retrieve the Contact Person from Maconomy"
                        ),
                        contacts_discovered=1,
                        failed_records=self._contact_records(
                            normalized_contact_number, None, "maconomy_contact_lookup"
                        ),
                    )
                raise HTTPException(
                    status_code=502,
                    detail="Unable to retrieve the Contact Person from Maconomy",
                ) from exc

            parent_number = str(contact.get("contactcompanynumber") or "").strip()
            email_text = str(contact.get(EMAIL_FIELD) or "").strip()
            if not email_text:
                return await self._manual_contact_validation_failure(
                    run_started,
                    normalized_contact_number,
                    parent_number,
                    "Contact Person has no email address",
                    "Contact Person does not have an email address",
                )
            if not parent_number:
                return await self._manual_contact_validation_failure(
                    run_started,
                    normalized_contact_number,
                    None,
                    "Contact Person has no parent Customer number",
                    "Contact Person does not have a parent Customer number",
                )

            try:
                back_query = await maconomy.get_contact_persons_by_emails(
                    [email_text]
                )
            except MaconomyError as exc:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="MACONOMY_CONTACT_LOOKUP",
                        error_message="Unable to resolve the email group in Maconomy",
                        contacts_discovered=1,
                        failed_records=self._contact_records(
                            normalized_contact_number,
                            parent_number,
                            "maconomy_contact_lookup",
                            reason=str(exc),
                        ),
                    )
                raise HTTPException(
                    status_code=502,
                    detail="Unable to resolve the email group in Maconomy",
                ) from exc

            consolidator = ContactConsolidator()
            group = ContactGroup(
                email=email_text.lower(),
                members=[contact],
            )
            group = consolidator.apply_back_query_results(
                group,
                back_query.get(group.email, []),
                changed_numbers={normalized_contact_number},
            )
            if group.unresolved or group.master_number is None:
                detail = (
                    "Unable to resolve MASTER for the email group: "
                    + (group.conflict_reason or "unknown conflict")
                )
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="MASTER_RESOLUTION",
                        error_message=detail,
                        contacts_discovered=1,
                        failed_records=self._contact_records(
                            normalized_contact_number,
                            parent_number,
                            "master_resolution",
                            reason=group.conflict_reason,
                        ),
                    )
                raise HTTPException(status_code=422, detail=detail)

            if group.master_number != normalized_contact_number:
                detail = (
                    f"Contact Person {normalized_contact_number} is routed to "
                    f"its MASTER {group.master_number}; synchronize the "
                    "MASTER instead"
                )
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="CONTACT_ROUTING",
                        error_message=detail,
                        contacts_discovered=1,
                        failed_records=self._contact_records(
                            normalized_contact_number,
                            parent_number,
                            "contact_routing",
                            reason=f"routed to master {group.master_number}",
                        ),
                    )
                raise HTTPException(status_code=422, detail=detail)

            try:
                parent_names = await maconomy.get_customer_names([parent_number])
            except MaconomyError as exc:
                ledger.add_error(
                    {
                        "entity_type": "customer",
                        "source_id": parent_number,
                        "stage": "maconomy_customer_lookup",
                        "message": str(exc),
                    }
                )
                parent_names = {}

            mapper = ContactMapper()
            master_record = mapper.enrich_contact(
                group.master_record or contact,
                parent_names.get(parent_number),
            )
            contact_payload = mapper.build_upsert_payload([master_record])
            if not contact_payload["inputs"]:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="CONTACT_MAPPING",
                        error_message=(
                            "Contact Person could not be mapped for HubSpot"
                        ),
                        contacts_discovered=1,
                        failed_records=self._contact_records(
                            normalized_contact_number,
                            parent_number,
                            "contact_mapping",
                        ),
                    )
                raise HTTPException(
                    status_code=422,
                    detail="Contact Person cannot be mapped for HubSpot",
                )

            try:
                contact_result = await hubspot.upsert_contacts(contact_payload)
            except HubSpotError as exc:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="HUBSPOT_CONTACT_UPSERT",
                        error_message=(
                            "Unable to synchronize the Contact with HubSpot"
                        ),
                        contacts_discovered=1,
                        failed_records=self._contact_records(
                            normalized_contact_number,
                            parent_number,
                            "hubspot_contact_upsert",
                        ),
                    )
                raise HTTPException(
                    status_code=502,
                    detail="Unable to synchronize the Contact with HubSpot",
                ) from exc

            contact_ids = hubspot.index_results_by_source_id(
                contact_result,
                trace_prefix="contact-",
                property_name="maconomy_contact_person_number",
            )
            contact_id = contact_ids.get(normalized_contact_number)
            if not contact_id:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="HUBSPOT_CONTACT_UPSERT",
                        error_message="HubSpot did not confirm the Contact upsert",
                        contacts_discovered=1,
                        failed_records=self._contact_records(
                            normalized_contact_number,
                            parent_number,
                            "hubspot_contact_upsert",
                        ),
                    )
                raise HTTPException(
                    status_code=502,
                    detail="HubSpot did not confirm the Contact upsert",
                )

            stamped_numbers, _ = await self._stamp_members(
                maconomy,
                [group],
                ledger,
            )
            await self._checkpoint_masters(maconomy, [group], ledger)

            try:
                company_ids = await hubspot.lookup_companies([parent_number])
            except HubSpotError as exc:
                if run_started:
                    await self._logger.fail_run(
                        failure_stage="HUBSPOT_COMPANY_LOOKUP",
                        error_message=(
                            "Unable to resolve the parent Company in HubSpot"
                        ),
                        contacts_discovered=1,
                        failed_records=[*ledger.errors],
                        successful_records=ledger.successful,
                    )
                raise HTTPException(
                    status_code=502,
                    detail="Unable to resolve the parent Company in HubSpot",
                ) from exc

            company_id = company_ids.get(parent_number)
            if not company_id:
                # STEP H: historical parent customer was never synced.
                company_id = await self._recover_manual_parent_company(
                    maconomy,
                    hubspot,
                    parent_number,
                    run_started,
                    ledger,
                )
            association_count = 0
            if not company_id:
                ledger.add_error(
                    {
                        "entity_type": "customer",
                        "source_id": parent_number,
                        "stage": "hubspot_company_lookup",
                        "message": "Parent Company was not found in HubSpot",
                    }
                )
            else:
                try:
                    await hubspot.associate_contact_to_company(
                        contact_id,
                        company_id,
                    )
                    association_count = 1
                    ledger.associations_succeeded += 1
                    ledger.add_success(
                        {
                            "entity_type": "contact",
                            "source_id": normalized_contact_number,
                            "parent_customer_number": parent_number,
                            "stage": "completed",
                            "message": (
                                "MASTER upsert, group stamping, and Company "
                                "association succeeded"
                            ),
                        }
                    )
                except HubSpotError as exc:
                    ledger.add_error(
                        {
                            "entity_type": "contact",
                            "source_id": normalized_contact_number,
                            "stage": "hubspot_association",
                            "message": str(exc),
                        }
                    )

            errors = ledger.errors
            if run_started:
                await self._logger.complete_run(
                    status="partial_success" if errors else "success",
                    contacts_discovered=1,
                    contacts_succeeded=ledger.contacts_succeeded,
                    associations_succeeded=association_count,
                    checkpoints_succeeded=ledger.checkpoints_succeeded,
                    skipped_count=0,
                    errors=errors,
                    skipped_records=ledger.skipped,
                    successful_records=ledger.successful,
                )
            return {
                "status": "partial_success" if errors else "success",
                "contact": {
                    "source_id": normalized_contact_number,
                    "master_number": group.master_number,
                    "parent_customer_number": parent_number,
                    "hubspot_id": contact_id,
                    "hubspot_upserted": True,
                    "company_associated": association_count > 0,
                    "group_members_stamped": len(stamped_numbers),
                    "checkpoint_written": ledger.checkpoints_succeeded > 0,
                },
                "errors": errors,
            }

    async def _manual_contact_validation_failure(
        self,
        run_started: bool,
        source_id: str,
        parent_number: str | None,
        error_message: str,
        http_detail: str,
    ) -> dict[str, Any]:
        if run_started:
            await self._logger.fail_run(
                failure_stage="CONTACT_VALIDATION",
                error_message=error_message,
                contacts_discovered=1,
                failed_records=self._contact_records(
                    source_id,
                    parent_number,
                    "contact_validation",
                ),
            )
        raise HTTPException(status_code=422, detail=http_detail)

    @staticmethod
    def _customer_records(
        customer_number: str,
        stage: str = "maconomy_customer_lookup",
    ) -> list[dict[str, Any]]:
        return [
            {
                "entity_type": "customer",
                "source_id": customer_number,
                "stage": stage,
            }
        ]

    @staticmethod
    def _contact_records(
        contact_number: str | None,
        parent_number: str | None,
        stage: str,
        reason: str | None = None,
    ) -> list[dict[str, Any]]:
        item: dict[str, Any] = {
            "entity_type": "contact",
            "source_id": contact_number,
            "stage": stage,
        }
        if parent_number:
            item["parent_customer_number"] = parent_number
        if reason:
            item["reason"] = reason
        return [item]

    @staticmethod
    def _parent_name_for(
        contact: dict[str, Any],
        customers_by_id: dict[str, dict[str, Any]],
        lookup_names: dict[str, str],
    ) -> str | None:
        """Resolve the master Contact's parent Customer name for HubSpot.

        Prefer the Customer already discovered in this run. Contacts whose
        parent is outside the discovery window use the targeted Maconomy name
        lookup performed by the contact branch.
        """
        parent_number = str(
            contact.get(CONTACT_COMPANY_NUMBER_FIELD) or ""
        ).strip()
        if not parent_number:
            return None

        customer = customers_by_id.get(parent_number) or {}
        discovered_name = str(customer.get("name1") or "").strip()
        if discovered_name:
            return discovered_name

        looked_up_name = str(lookup_names.get(parent_number) or "").strip()
        return looked_up_name or None

    async def _resolve_groups_with_back_query(
        self,
        maconomy: MaconomyService,
        groups: list[ContactGroup],
        changed_numbers: set[str],
        ledger: _RunLedger,
    ) -> list[ContactGroup]:
        consolidator = ContactConsolidator()
        back_query_emails = consolidator.needs_back_query_emails(groups)
        if not back_query_emails:
            return groups

        try:
            back_query = await maconomy.get_contact_persons_by_emails(
                back_query_emails
            )
        except MaconomyError as exc:
            message = str(exc) or "Maconomy request failed"
            for group in groups:
                if not group.needs_back_query:
                    continue
                group.unresolved = True
                group.conflict_reason = "email back-query failed"
                for member in group.members:
                    ledger.add_skip(
                        {
                            "entity_type": "contact",
                            "source_id": str(
                                member.get(CONTACT_PERSON_NUMBER_FIELD) or ""
                            ).strip(),
                            "reason": f"email back-query failed: {message}",
                        }
                    )
            return groups

        resolved: list[ContactGroup] = []
        for group in groups:
            if not group.needs_back_query:
                resolved.append(group)
                continue
            resolved.append(
                consolidator.apply_back_query_results(
                    group,
                    back_query.get(group.email, []),
                    changed_numbers,
                )
            )
        final_groups: list[ContactGroup] = []
        for group in resolved:
            if group.unresolved:
                for member in group.members:
                    ledger.add_skip(
                        {
                            "entity_type": "contact",
                            "source_id": str(
                                member.get(CONTACT_PERSON_NUMBER_FIELD) or ""
                            ).strip(),
                            "reason": (
                                group.conflict_reason
                                or "master could not be resolved"
                            ),
                        }
                    )
            final_groups.append(group)
        return final_groups

    async def _recover_manual_parent_company(
        self,
        maconomy: MaconomyService,
        hubspot: HubSpotService,
        parent_number: str,
        run_started: bool,
        ledger: _RunLedger,
    ) -> str | None:
        """STEP H for the manual contact flow: never-synced parent recovery."""
        try:
            records = await maconomy.get_customers_by_numbers([parent_number])
        except MaconomyError as exc:
            if run_started:
                await self._logger.fail_run(
                    failure_stage="HISTORICAL_PARENT_RECOVERY",
                    error_message=(
                        "Unable to fetch the parent Customer from Maconomy"
                    ),
                    contacts_discovered=1,
                    failed_records=[
                        {
                            "entity_type": "customer",
                            "source_id": parent_number,
                            "stage": "historical_parent_recovery",
                            "reason": str(exc),
                        },
                        *ledger.errors,
                    ],
                    successful_records=ledger.successful,
                )
            raise HTTPException(
                status_code=502,
                detail="Unable to fetch the parent Customer from Maconomy",
            ) from exc

        record = records.get(parent_number)
        if record is None:
            ledger.add_skip(
                {
                    "entity_type": "customer",
                    "source_id": parent_number,
                    "stage": "historical_parent_recovery",
                    "reason": (
                        "Parent Customer was not found in Maconomy; "
                        "association skipped"
                    ),
                }
            )
            ledger.add_error(
                {
                    "entity_type": "customer",
                    "source_id": parent_number,
                    "stage": "hubspot_company_lookup",
                    "message": "Parent Company was not found in HubSpot",
                }
            )
            return None

        payload = CompanyMapper().build_upsert_payload([record])
        for skipped in payload["skipped"]:
            ledger.add_error(
                {
                    "entity_type": "customer",
                    "source_id": parent_number,
                    "stage": "historical_parent_recovery",
                    "message": (
                        str(skipped.get("reason") or "") or "mapping failed"
                    ),
                }
            )
        if not payload["inputs"]:
            return None

        try:
            result = await hubspot.upsert_companies(payload)
        except HubSpotError as exc:
            if run_started:
                await self._logger.fail_run(
                    failure_stage="HISTORICAL_PARENT_RECOVERY",
                    error_message=(
                        "Unable to create the parent Company in HubSpot"
                    ),
                    contacts_discovered=1,
                    failed_records=[
                        {
                            "entity_type": "customer",
                            "source_id": parent_number,
                            "stage": "historical_parent_recovery",
                            "reason": str(exc),
                        },
                        *ledger.errors,
                    ],
                    successful_records=ledger.successful,
                )
            raise HTTPException(
                status_code=502,
                detail="Unable to create the parent Company in HubSpot",
            ) from exc

        recovered_ids = hubspot.index_results_by_source_id(
            result,
            trace_prefix="company-",
            property_name="maconomy_customer_number",
        )
        company_id = recovered_ids.get(parent_number)
        if not company_id:
            ledger.add_error(
                {
                    "entity_type": "customer",
                    "source_id": parent_number,
                    "stage": "hubspot_upsert",
                    "message": (
                        "HubSpot did not confirm the parent Company upsert"
                    ),
                }
            )
            return None

        ledger.add_success(
            {
                "entity_type": "customer",
                "source_id": parent_number,
                "stage": "historical_parent_recovery",
                "message": (
                    "Historical parent Company created in HubSpot "
                    "before association"
                ),
            }
        )
        try:
            await maconomy.update_customer_sync_version(parent_number)
            ledger.checkpoints_succeeded += 1
            ledger.customers_succeeded += 1
            ledger.add_success(
                {
                    "entity_type": "customer",
                    "source_id": parent_number,
                    "stage": "historical_parent_recovery",
                    "message": (
                        "customerremark26 = versionnumber + 1 written for "
                        "historical parent Customer"
                    ),
                }
            )
        except MaconomyError as exc:
            ledger.add_error(
                {
                    "entity_type": "customer",
                    "source_id": parent_number,
                    "stage": "maconomy_checkpoint",
                    "message": str(exc),
                }
            )
        return company_id

    async def _run_company_branch(
        self,
        hubspot: HubSpotService,
        maconomy: MaconomyService,
        all_customers: list[dict[str, Any]],
        customers_by_id: dict[str, dict[str, Any]],
        ledger: _RunLedger,
    ) -> dict[str, Any]:
        company_ids: dict[str, str] = {}
        customer_checkpoint_ids: set[str] = set()

        company_payload = CompanyMapper().build_upsert_payload(all_customers)
        for skipped in company_payload["skipped"]:
            record = skipped.get("record") or {}
            ledger.add_skip(
                {
                    "entity_type": "customer",
                    "source_id": str(
                        record.get(CUSTOMER_NUMBER_FIELD) or ""
                    ).strip(),
                    "reason": str(skipped.get("reason") or "mapping failed"),
                }
            )

        try:
            if company_payload["inputs"]:
                companies_result = await hubspot.upsert_companies(company_payload)
                company_ids = hubspot.index_results_by_source_id(
                    companies_result,
                    trace_prefix="company-",
                    property_name="maconomy_customer_number",
                )
        except HubSpotError as exc:
            raise _BranchFailure(
                stage="HUBSPOT_COMPANY_UPSERT",
                message="Unable to synchronize Companies with HubSpot",
                customers_discovered=len(customers_by_id),
                contacts_discovered=0,
                failed_records=[
                    self._customer_records(number)[0]
                    for number in sorted(customers_by_id)
                ],
                cause=str(exc),
            ) from exc

        for customer_number in sorted(set(customers_by_id) - set(company_ids)):
            ledger.add_error(
                {
                    "entity_type": "customer",
                    "source_id": customer_number,
                    "stage": "hubspot_upsert",
                    "message": "HubSpot did not confirm the Company upsert",
                }
            )

        for customer_number in sorted(company_ids):
            customer = customers_by_id.get(customer_number)
            if customer is None:
                continue
            try:
                await maconomy.update_customer_sync_version(customer_number)
                customer_checkpoint_ids.add(customer_number)
                ledger.checkpoints_succeeded += 1
                ledger.customers_succeeded += 1
                ledger.add_success(
                    {
                        "entity_type": "customer",
                        "source_id": customer_number,
                        "stage": "completed",
                        "message": (
                            "Company upsert and Maconomy write-back succeeded"
                        ),
                    }
                )
            except MaconomyError as exc:
                ledger.add_error(
                    {
                        "entity_type": "customer",
                        "source_id": customer_number,
                        "stage": "maconomy_checkpoint",
                        "message": str(exc),
                    }
                )
        return {
            "company_ids": company_ids,
            "customer_checkpoint_ids": customer_checkpoint_ids,
        }

    async def _run_contact_branch(
        self,
        maconomy: MaconomyService,
        hubspot: HubSpotService,
        consolidator: ContactConsolidator,
        groups: list[ContactGroup],
        customers_by_id: dict[str, dict[str, Any]],
        ledger: _RunLedger,
    ) -> _ContactBranchState:
        state = _ContactBranchState(groups=groups)
        sync_groups = [group for group in groups if group.action == "sync_master"]
        stamp_only_groups = [
            group for group in groups if group.action == "stamp_only"
        ]

        master_pairs: list[tuple[ContactGroup, dict[str, Any]]] = []
        for group in sync_groups:
            master_record = group.master_record
            if master_record is None:
                ledger.add_error(
                    {
                        "entity_type": "contact",
                        "source_id": group.master_number,
                        "stage": "master_resolution",
                        "message": "master record is not available for upsert",
                    }
                )
                continue
            master_pairs.append((group, master_record))

        missing_parents = sorted(
            {
                str(master_record.get("contactcompanynumber") or "").strip()
                for _, master_record in master_pairs
                if str(master_record.get("contactcompanynumber") or "").strip()
                not in customers_by_id
            }
        )
        lookup_names: dict[str, str] = {}
        if missing_parents:
            try:
                lookup_names = await maconomy.get_customer_names(missing_parents)
            except MaconomyError:
                ledger.add_error(
                    {
                        "entity_type": "customer",
                        "source_id": None,
                        "stage": "maconomy_customer_lookup",
                        "message": (
                            "Unable to resolve parent customer names; masters "
                            "synced without companyname"
                        ),
                    }
                )

        mapper = ContactMapper()
        enriched_masters = [
            mapper.enrich_contact(
                master_record,
                self._parent_name_for(
                    master_record,
                    customers_by_id,
                    lookup_names,
                ),
            )
            for _, master_record in master_pairs
        ]
        contact_payload = mapper.build_upsert_payload(enriched_masters)
        for skipped in contact_payload["skipped"]:
            record = skipped.get("record") or {}
            ledger.add_error(
                {
                    "entity_type": "contact",
                    "source_id": str(
                        record.get(CONTACT_PERSON_NUMBER_FIELD) or ""
                    ).strip(),
                    "stage": "contact_mapping",
                    "message": str(skipped.get("reason") or "mapping failed"),
                }
            )

        try:
            if contact_payload["inputs"]:
                contacts_result = await hubspot.upsert_contacts(contact_payload)
                state.contact_ids = hubspot.index_results_by_source_id(
                    contacts_result,
                    trace_prefix="contact-",
                    property_name="maconomy_contact_person_number",
                )
        except HubSpotError as exc:
            raise _BranchFailure(
                stage="HUBSPOT_CONTACT_UPSERT",
                message="Unable to synchronize Contacts with HubSpot",
                customers_discovered=0,
                contacts_discovered=sum(
                    len(group.member_numbers()) for group in groups
                ),
                failed_records=[
                    {
                        "entity_type": "contact",
                        "source_id": group.master_number,
                        "stage": "hubspot_contact_upsert",
                    }
                    for group in sync_groups
                ],
                cause=str(exc),
            ) from exc

        confirmed_masters = {
            group.master_number
            for group in sync_groups
            if group.master_number in state.contact_ids
        }
        for group in sync_groups:
            if (
                group.master_number
                and group.master_number not in confirmed_masters
            ):
                ledger.add_error(
                    {
                        "entity_type": "contact",
                        "source_id": group.master_number,
                        "stage": "hubspot_upsert",
                        "message": "HubSpot did not confirm the Contact upsert",
                    }
                )

        stampable_sync_groups = [
            group
            for group in sync_groups
            if group.master_number in confirmed_masters
        ]
        stamped_sync, _ = await self._stamp_members(
            maconomy,
            stampable_sync_groups,
            ledger,
        )
        stamped_stamp_only, _ = await self._stamp_members(
            maconomy,
            stamp_only_groups,
            ledger,
        )
        state.checkpointed_masters = await self._checkpoint_masters(
            maconomy,
            stampable_sync_groups,
            ledger,
        )
        state.stamped_numbers = stamped_sync | stamped_stamp_only
        state.group_summaries = [
            {
                "master_contact_person_number": group.master_number,
                "action": group.action,
                "members": len(group.member_numbers()),
                "upserted": (
                    group.master_number in state.contact_ids
                    if group.master_number
                    else False
                ),
                "stamped_members": len(
                    state.stamped_numbers & group.member_numbers()
                ),
            }
            for group in groups
        ]
        return state

    async def _stamp_members(
        self,
        maconomy: MaconomyService,
        groups: list[ContactGroup],
        ledger: _RunLedger,
    ) -> tuple[set[str], int]:
        """Write remark4 = master number on stamp targets.

        Default mode stamps members with an EMPTY remark4 only. Groups that
        went through re-election (stamp_mode = overwrite) stamp every member
        so the routing points at the new master."""
        semaphore = asyncio.Semaphore(MID_RUN_BACK_QUERY_CONCURRENCY)
        stamped_numbers: set[str] = set()

        async def stamp_one(
            member: dict[str, Any],
            master_number: str,
        ) -> None:
            member_number = str(
                member.get(CONTACT_PERSON_NUMBER_FIELD) or ""
            ).strip()
            if not member_number:
                return
            try:
                async with semaphore:
                    await maconomy.write_contact_master_stamp(
                        member_number,
                        master_number,
                    )
                stamped_numbers.add(member_number)
                ledger.checkpoints_succeeded += 1
                ledger.add_success(
                    {
                        "entity_type": "contact",
                        "source_id": member_number,
                        "stage": "completed",
                        "message": f"remark4 stamped with master {master_number}",
                    }
                )
            except MaconomyError as exc:
                ledger.add_error(
                    {
                        "entity_type": "contact",
                        "source_id": member_number,
                        "stage": "contact_master_stamp",
                        "message": str(exc),
                    }
                )

        tasks: list[Any] = []
        for group in groups:
            master_number = group.master_number
            if not master_number:
                continue
            for member in group.members_to_stamp():
                tasks.append(stamp_one(member, master_number))
        if tasks:
            await asyncio.gather(*tasks)

        contacts_succeeded = len(stamped_numbers)
        ledger.contacts_succeeded += contacts_succeeded
        return stamped_numbers, contacts_succeeded

    async def _checkpoint_masters(
        self,
        maconomy: MaconomyService,
        groups: list[ContactGroup],
        ledger: _RunLedger,
    ) -> set[str]:
        """Write remark5 = versionnumber + 1 for confirmed masters only."""
        checkpointed: set[str] = set()
        for group in sorted(
            groups,
            key=lambda item: item.master_number or "",
        ):
            master_number = group.master_number
            if not master_number:
                continue
            try:
                await maconomy.write_contact_sync_checkpoint(master_number)
                checkpointed.add(master_number)
                ledger.checkpoints_succeeded += 1
                ledger.add_success(
                    {
                        "entity_type": "contact",
                        "source_id": master_number,
                        "stage": "completed",
                        "message": "remark5 sync checkpoint written",
                    }
                )
            except MaconomyError as exc:
                ledger.add_error(
                    {
                        "entity_type": "contact",
                        "source_id": master_number,
                        "stage": "maconomy_checkpoint",
                        "message": str(exc),
                    }
                )
        return checkpointed

    async def _recover_historical_parents(
        self,
        maconomy: MaconomyService,
        hubspot: HubSpotService,
        numbers: list[str],
        company_ids: dict[str, str],
        ledger: _RunLedger,
    ) -> None:
        """STEP H: create HubSpot Companies for parents never synced.

        Historical parent customers are not part of the 2-day discovery
        window. Fetch them from Maconomy by number, upsert them as
        Companies, checkpoint customerremark26, and merge the confirmed
        IDs into company_ids so association mapping can proceed."""
        if not numbers:
            return

        try:
            records = await maconomy.get_customers_by_numbers(numbers)
        except MaconomyError as exc:
            message = str(exc) or "Maconomy request failed"
            for number in numbers:
                ledger.add_error(
                    {
                        "entity_type": "customer",
                        "source_id": number,
                        "stage": "historical_parent_recovery",
                        "message": (
                            "Unable to fetch historical parent Customer "
                            f"from Maconomy: {message}"
                        ),
                    }
                )
            return

        for number in numbers:
            if number not in records:
                ledger.add_skip(
                    {
                        "entity_type": "customer",
                        "source_id": number,
                        "stage": "historical_parent_recovery",
                        "reason": (
                            "Parent Customer was not found in Maconomy; "
                            "association skipped"
                        ),
                    }
                )

        recovered = list(records.values())
        payload = CompanyMapper().build_upsert_payload(recovered)
        for skipped in payload["skipped"]:
            record = skipped.get("record") or {}
            ledger.add_error(
                {
                    "entity_type": "customer",
                    "source_id": str(
                        record.get(CUSTOMER_NUMBER_FIELD) or ""
                    ).strip(),
                    "stage": "historical_parent_recovery",
                    "message": str(skipped.get("reason") or "mapping failed"),
                }
            )
        if not payload["inputs"]:
            return

        try:
            result = await hubspot.upsert_companies(payload)
        except HubSpotError as exc:
            for number in sorted(records):
                ledger.add_error(
                    {
                        "entity_type": "customer",
                        "source_id": number,
                        "stage": "historical_parent_recovery",
                        "message": (
                            "Unable to upsert historical parent Company "
                            f"in HubSpot: {exc}"
                        ),
                    }
                )
            return

        recovered_ids = hubspot.index_results_by_source_id(
            result,
            trace_prefix="company-",
            property_name="maconomy_customer_number",
        )
        confirmed = {
            number: company_id
            for number, company_id in recovered_ids.items()
            if number in records
        }
        for number, _company_id in confirmed.items():
            ledger.add_success(
                {
                    "entity_type": "customer",
                    "source_id": number,
                    "stage": "historical_parent_recovery",
                    "message": (
                        "Historical parent Company created in HubSpot "
                        "before association"
                    ),
                }
            )
        for number in sorted(set(records) - set(confirmed)):
            ledger.add_error(
                {
                    "entity_type": "customer",
                    "source_id": number,
                    "stage": "hubspot_upsert",
                    "message": (
                        "HubSpot did not confirm the historical parent "
                        "Company upsert"
                    ),
                }
            )
        company_ids.update(confirmed)
        if not confirmed:
            return

        for number in sorted(confirmed):
            try:
                await maconomy.update_customer_sync_version(number)
                ledger.checkpoints_succeeded += 1
                ledger.customers_succeeded += 1
                ledger.add_success(
                    {
                        "entity_type": "customer",
                        "source_id": number,
                        "stage": "historical_parent_recovery",
                        "message": (
                            "customerremark26 = versionnumber + 1 written "
                            "for historical parent Customer"
                        ),
                    }
                )
            except MaconomyError as exc:
                ledger.add_error(
                    {
                        "entity_type": "customer",
                        "source_id": number,
                        "stage": "maconomy_checkpoint",
                        "message": str(exc),
                    }
                )

    async def _run_association_phase(
        self,
        maconomy: MaconomyService,
        hubspot: HubSpotService,
        groups: list[ContactGroup],
        company_ids: dict[str, str],
        contact_state: _ContactBranchState,
        ledger: _RunLedger,
    ) -> dict[str, Any]:
        usable = [group for group in groups if not group.unresolved]
        contact_ids = contact_state.contact_ids

        masters_missing = [
            group.master_number
            for group in usable
            if group.master_number and group.master_number not in contact_ids
        ]
        existing_contact_ids: dict[str, str] = {}
        if masters_missing:
            try:
                existing_contact_ids = await hubspot.lookup_contacts(
                    masters_missing
                )
            except HubSpotError as exc:
                ledger.add_error(
                    {
                        "entity_type": "contact",
                        "source_id": "",
                        "stage": "hubspot_contact_lookup",
                        "message": f"HubSpot contact lookup failed: {exc}",
                    }
                )

        needed_companies: set[str] = set()
        for group in usable:
            master_number = group.master_number
            if master_number and (
                master_number in contact_ids
                or master_number in existing_contact_ids
            ):
                needed_companies.update(group.parent_companies())
        missing_companies = [
            number
            for number in sorted(needed_companies)
            if number not in company_ids
        ]
        if missing_companies:
            try:
                looked_up = await hubspot.lookup_companies(missing_companies)
                company_ids = {**company_ids, **looked_up}
            except HubSpotError as exc:
                ledger.add_error(
                    {
                        "entity_type": "customer",
                        "source_id": "",
                        "stage": "hubspot_company_lookup",
                        "message": f"HubSpot company lookup failed: {exc}",
                    }
                )

        await self._recover_historical_parents(
            maconomy,
            hubspot,
            [number for number in sorted(needed_companies) if number not in company_ids],
            company_ids,
            ledger,
        )

        attempted_pairs: list[tuple[ContactGroup, str]] = []
        for group in usable:
            master_number = group.master_number
            if not master_number:
                continue
            if (
                master_number not in contact_ids
                and master_number not in existing_contact_ids
            ):
                ledger.add_error(
                    {
                        "entity_type": "contact",
                        "source_id": master_number,
                        "stage": "hubspot_contact_lookup",
                        "message": (
                            "MASTER is not confirmed in HubSpot; "
                            "association skipped"
                        ),
                    }
                )
                continue
            for parent_number in sorted(group.parent_companies()):
                if parent_number not in company_ids:
                    ledger.add_error(
                        {
                            "entity_type": "customer",
                            "source_id": parent_number,
                            "stage": "hubspot_company_lookup",
                            "message": "Parent Company was not found in HubSpot",
                        }
                    )
                    continue
                attempted_pairs.append((group, parent_number))

        semaphore = asyncio.Semaphore(MID_RUN_BACK_QUERY_CONCURRENCY)

        async def associate(
            group: ContactGroup,
            parent_number: str,
        ) -> None:
            master_number = group.master_number or ""
            master_id = contact_ids.get(master_number) or (
                existing_contact_ids.get(master_number)
            )
            company_id = company_ids.get(parent_number)
            if not master_id or not company_id:
                return
            try:
                async with semaphore:
                    await hubspot.associate_contact_to_company(
                        master_id,
                        company_id,
                    )
                ledger.associations_succeeded += 1
                group.associated_companies.append(parent_number)
            except HubSpotError as exc:
                ledger.add_error(
                    {
                        "entity_type": "contact",
                        "source_id": master_number,
                        "stage": "hubspot_association",
                        "message": str(exc),
                    }
                )

        tasks = [associate(group, parent) for group, parent in attempted_pairs]
        if tasks:
            await asyncio.gather(*tasks)

        return {
            "attempted": len(attempted_pairs),
            "succeeded": ledger.associations_succeeded,
        }

    def _bulk_result(
        self,
        status: str,
        ledger: _RunLedger,
        company_ids: dict[str, str],
        contact_state: _ContactBranchState,
        groups: list[ContactGroup],
        association_pairs: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "status": status,
            "sync_window_days": 2,
            "classification": {
                "customers_discovered": ledger.customers_discovered,
                "contacts_discovered": ledger.contacts_discovered,
                "email_groups": len(groups),
                "stamped_contacts": len(contact_state.stamped_numbers),
            },
            "hubspot": {
                "companies_upserted": len(company_ids),
                "contact_masters_upserted": len(contact_state.contact_ids),
                "associations_attempted": association_pairs.get("attempted", 0),
                "associations_succeeded": association_pairs.get("succeeded", 0),
            },
            "maconomy_checkpoints": {
                "customers": ledger.customers_succeeded,
                "masters_remark5": len(contact_state.checkpointed_masters),
                "stamped_members": len(contact_state.stamped_numbers),
            },
            "group_summaries": contact_state.group_summaries,
            "skipped": ledger.skipped,
            "errors": ledger.errors,
        }
