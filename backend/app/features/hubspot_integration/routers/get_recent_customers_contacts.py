import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.integration_services import (
    IntegrationServiceIdentifier,
    require_active_integration_service,
)
from app.features.hubspot_integration.mappers.dynamic_field_mapper import (
    map_contacts_to_upsert,
    map_customers_to_company_upsert,
)
from app.features.hubspot_integration.services.hubspot_service import (
    HubSpotService,
    HubSpotServiceError,
)
from app.features.hubspot_integration.services.maconomy_service import (
    MaconomyService,
    MaconomyServiceError,
)
from app.features.hubspot_integration.services import integration_run_log_service


router = APIRouter(
    prefix="/hubspot",
    tags=["hubspot-integration"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


def _records_by_id(
    records: list[dict[str, Any]],
    id_field: str,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        source_id = str(record.get(id_field) or "").strip()
        if source_id:
            indexed[source_id] = record
    return indexed


def _deduplicate_contacts(
    contacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    indexed = _records_by_id(contacts, "contactpersonnumber")
    return list(indexed.values())


def _sanitize_mapper_skips(
    skips: list[dict[str, Any]],
    *,
    entity_type: str,
    id_field: str,
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in skips:
        record = item.get("record", {})
        source_id = (
            str(record.get(id_field) or "").strip()
            if isinstance(record, dict)
            else ""
        )
        sanitized.append(
            {
                "entity_type": entity_type,
                "source_id": source_id or None,
                "reason": str(item.get("reason") or "mapping failed"),
            }
        )
    return sanitized


@router.post(
    "/sync/customers",
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_HUBSPOT_SYNC
            )
        )
    ],
)
async def sync_customers_to_hubspot(
    request: Request,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Synchronize changed Maconomy Customers and Contacts to HubSpot."""
    request_id = getattr(request.state, "request_id", uuid.uuid4())
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.UUID(str(request_id))
    trigger_header = request.headers.get("X-Integration-Trigger", "API").upper()
    trigger_type = "SCHEDULER" if trigger_header == "SCHEDULER" else "API"
    run_log = await integration_run_log_service.start_run(
        session,
        request_id=request_id,
        maconomy_instance=get_settings().maconomy_shortname,
        operation="BULK_SYNC",
        trigger_type=trigger_type,
    )
    errors: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        maconomy = MaconomyService(client)
        hubspot = HubSpotService(client)

        try:
            candidates = await maconomy.get_sync_candidates()
        except MaconomyServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="MACONOMY_DISCOVERY",
                error_message="Unable to retrieve Customers and Contacts",
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve customers and contacts from Maconomy",
            ) from exc

        new_customers = candidates["new_customers"]
        updated_customers = candidates["updated_customers"]
        new_contacts_for_existing = candidates[
            "new_contacts_for_existing_customers"
        ]
        updated_contacts = candidates["updated_contacts"]

        all_customers = [*new_customers, *updated_customers]
        customers_by_id = _records_by_id(all_customers, "customernumber")
        new_customer_ids = set(
            _records_by_id(new_customers, "customernumber")
        )

        company_payload = map_customers_to_company_upsert(
            new_customers,
            updated_customers,
        )
        companies_result: dict[str, Any] = {
            "requested": 0,
            "status": 200,
            "result": {"results": [], "errors": []},
        }

        try:
            if company_payload["inputs"]:
                companies_result = await hubspot.upsert_companies(
                    {"inputs": company_payload["inputs"]}
                )
        except HubSpotServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="HUBSPOT_COMPANY_UPSERT",
                error_message="Unable to synchronize Companies with HubSpot",
                customers_discovered=len(all_customers),
                failed_records=[
                    {
                        "entity_type": "customer",
                        "source_id": customer_number,
                        "stage": "hubspot_company_upsert",
                    }
                    for customer_number in customers_by_id
                ],
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to synchronize Companies with HubSpot",
            ) from exc

        company_ids = hubspot.index_results_by_source_id(
            companies_result,
            property_name="maconomy_customer_number",
            trace_prefix="company-",
        )
        successful_customer_ids = set(company_ids)
        failed_customer_ids = set(customers_by_id) - successful_customer_ids
        errors.extend(
            {
                "entity_type": "customer",
                "source_id": customer_number,
                "stage": "hubspot_upsert",
                "message": "HubSpot did not confirm the Company upsert",
            }
            for customer_number in sorted(failed_customer_ids)
        )

        customer_checkpoint_ids: set[str] = set()
        for customer_number in successful_customer_ids:
            customer = customers_by_id.get(customer_number)
            if customer is None:
                continue
            try:
                await maconomy.update_customer_sync_version(
                    customer_number,
                    customer.get("versionnumber"),
                )
                customer_checkpoint_ids.add(customer_number)
            except MaconomyServiceError as exc:
                errors.append(
                    {
                        "entity_type": "customer",
                        "source_id": customer_number,
                        "stage": "maconomy_checkpoint",
                        "message": str(exc),
                    }
                )

        contacts_for_new_customers = [
            contact
            for customer in new_customers
            for contact in customer.get("contactperson", [])
        ]
        all_contacts = _deduplicate_contacts(
            [
                *contacts_for_new_customers,
                *new_contacts_for_existing,
                *updated_contacts,
            ]
        )
        contacts_by_id = _records_by_id(
            all_contacts,
            "contactpersonnumber",
        )

        required_parent_numbers = {
            str(contact.get("contactcompanynumber") or "").strip()
            for contact in all_contacts
            if str(contact.get("contactcompanynumber") or "").strip()
        }
        existing_parent_numbers = sorted(
            parent_number
            for parent_number in required_parent_numbers
            if parent_number not in company_ids
            and parent_number not in new_customer_ids
        )

        try:
            if existing_parent_numbers:
                company_ids.update(
                    await hubspot.lookup_companies(existing_parent_numbers)
                )
        except HubSpotServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="HUBSPOT_COMPANY_LOOKUP",
                error_message="Unable to resolve existing Companies in HubSpot",
                customers_discovered=len(all_customers),
                contacts_discovered=len(all_contacts),
                failed_records=[
                    *errors,
                    *[
                        {
                            "entity_type": "contact",
                            "source_id": str(
                                contact.get("contactpersonnumber") or ""
                            ).strip(),
                            "parent_customer_number": str(
                                contact.get("contactcompanynumber") or ""
                            ).strip(),
                            "stage": "hubspot_company_lookup",
                        }
                        for contact in all_contacts
                        if str(
                            contact.get("contactcompanynumber") or ""
                        ).strip() in existing_parent_numbers
                    ],
                ],
                successful_records=[
                    {
                        "entity_type": "customer",
                        "source_id": customer_number,
                        "stage": "completed",
                    }
                    for customer_number in customer_checkpoint_ids
                ],
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to resolve existing Companies in HubSpot",
            ) from exc

        eligible_contacts: list[dict[str, Any]] = []
        unresolved_contacts: list[dict[str, Any]] = []
        for contact in all_contacts:
            contact_number = str(
                contact.get("contactpersonnumber") or ""
            ).strip()
            parent_number = str(
                contact.get("contactcompanynumber") or ""
            ).strip()
            if not parent_number or parent_number not in company_ids:
                unresolved_contacts.append(
                    {
                        "entity_type": "contact",
                        "source_id": contact_number or None,
                        "reason": "parent Company was not resolved in HubSpot",
                    }
                )
                continue
            eligible_contacts.append(contact)

        contact_payload = map_contacts_to_upsert(eligible_contacts)
        contacts_result: dict[str, Any] = {
            "requested": 0,
            "status": 200,
            "result": {"results": [], "errors": []},
        }

        try:
            if contact_payload["inputs"]:
                contacts_result = await hubspot.upsert_contacts(
                    {"inputs": contact_payload["inputs"]}
                )
        except HubSpotServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="HUBSPOT_CONTACT_UPSERT",
                error_message="Unable to synchronize Contacts with HubSpot",
                customers_discovered=len(all_customers),
                contacts_discovered=len(all_contacts),
                failed_records=[
                    *errors,
                    *[
                        {
                            "entity_type": "contact",
                            "source_id": str(
                                contact.get("contactpersonnumber") or ""
                            ).strip(),
                            "parent_customer_number": str(
                                contact.get("contactcompanynumber") or ""
                            ).strip(),
                            "stage": "hubspot_contact_upsert",
                        }
                        for contact in eligible_contacts
                    ],
                ],
                successful_records=[
                    {
                        "entity_type": "customer",
                        "source_id": customer_number,
                        "stage": "completed",
                    }
                    for customer_number in customer_checkpoint_ids
                ],
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to synchronize Contacts with HubSpot",
            ) from exc

        contact_ids = hubspot.index_results_by_source_id(
            contacts_result,
            property_name="maconomy_contact_person_number",
            trace_prefix="contact-",
        )
        eligible_contact_ids = set(
            _records_by_id(eligible_contacts, "contactpersonnumber")
        )
        failed_contact_ids = eligible_contact_ids - set(contact_ids)
        errors.extend(
            {
                "entity_type": "contact",
                "source_id": contact_number,
                "stage": "hubspot_upsert",
                "message": "HubSpot did not confirm the Contact upsert",
            }
            for contact_number in sorted(failed_contact_ids)
        )

        associated_contact_ids: set[str] = set()
        for contact_number, contact_id in contact_ids.items():
            contact = contacts_by_id.get(contact_number)
            if contact is None:
                continue
            parent_number = str(
                contact.get("contactcompanynumber") or ""
            ).strip()
            company_id = company_ids.get(parent_number)
            if not company_id:
                continue
            try:
                await hubspot.associate_contact_to_company(
                    contact_id,
                    company_id,
                )
                associated_contact_ids.add(contact_number)
            except HubSpotServiceError as exc:
                errors.append(
                    {
                        "entity_type": "contact",
                        "source_id": contact_number,
                        "stage": "hubspot_association",
                        "message": str(exc),
                    }
                )

        contact_checkpoint_ids: set[str] = set()
        for contact_number in associated_contact_ids:
            contact = contacts_by_id.get(contact_number)
            if contact is None:
                continue
            try:
                await maconomy.update_contact_sync_version(
                    contact_number,
                    contact.get("versionnumber"),
                )
                contact_checkpoint_ids.add(contact_number)
            except MaconomyServiceError as exc:
                errors.append(
                    {
                        "entity_type": "contact",
                        "source_id": contact_number,
                        "stage": "maconomy_checkpoint",
                        "message": str(exc),
                    }
                )

        skipped = [
            *candidates["skipped"],
            *_sanitize_mapper_skips(
                company_payload["skipped"],
                entity_type="customer",
                id_field="customernumber",
            ),
            *_sanitize_mapper_skips(
                contact_payload["skipped"],
                entity_type="contact",
                id_field="contactpersonnumber",
            ),
            *unresolved_contacts,
        ]
        for item in [*errors, *skipped]:
            if item.get("entity_type") != "contact":
                continue
            source_id = str(item.get("source_id") or "").strip()
            contact = contacts_by_id.get(source_id)
            if contact is None:
                continue
            parent_number = str(
                contact.get("contactcompanynumber") or ""
            ).strip()
            if parent_number:
                item.setdefault("parent_customer_number", parent_number)

        successful_records = [
            *[
                {
                    "entity_type": "customer",
                    "source_id": customer_number,
                    "stage": "completed",
                    "message": "Company upsert and Maconomy writeback succeeded",
                }
                for customer_number in customer_checkpoint_ids
            ],
            *[
                {
                    "entity_type": "contact",
                    "source_id": contact_number,
                    "parent_customer_number": str(
                        contacts_by_id[contact_number].get(
                            "contactcompanynumber"
                        ) or ""
                    ).strip(),
                    "stage": "completed",
                    "message": (
                        "Contact upsert, Company association, and Maconomy "
                        "writeback succeeded"
                    ),
                }
                for contact_number in contact_checkpoint_ids
                if contact_number in contacts_by_id
            ],
        ]

        result = {
            "status": (
                "partial_success"
                if errors or unresolved_contacts
                else "success"
            ),
            "sync_window_days": 2,
            "classification": {
                "new_customers": len(new_customers),
                "updated_customers": len(updated_customers),
                "new_contacts_for_existing_customers": len(
                    new_contacts_for_existing
                ),
                "updated_contacts": len(updated_contacts),
                "contacts_for_new_customers": len(
                    contacts_for_new_customers
                ),
            },
            "hubspot": {
                "companies_requested": companies_result.get("requested", 0),
                "companies_succeeded": len(successful_customer_ids),
                "contacts_requested": contacts_result.get("requested", 0),
                "contacts_succeeded": len(contact_ids),
                "contacts_associated": len(associated_contact_ids),
            },
            "maconomy_checkpoints": {
                "customers": len(customer_checkpoint_ids),
                "contacts": len(contact_checkpoint_ids),
            },
            "skipped": skipped,
            "errors": errors,
        }
        await integration_run_log_service.complete_run(
            session,
            run_log,
            status=result["status"],
            customers_discovered=len(all_customers),
            customers_succeeded=len(customer_checkpoint_ids),
            contacts_discovered=len(all_contacts),
            contacts_succeeded=len(contact_checkpoint_ids),
            associations_succeeded=len(associated_contact_ids),
            checkpoints_succeeded=(
                len(customer_checkpoint_ids) + len(contact_checkpoint_ids)
            ),
            skipped_count=len(skipped),
            errors=errors,
            skipped_records=skipped,
            successful_records=successful_records,
        )
        return result
