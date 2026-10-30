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
    enrich_contacts_with_parent_company_name,
    map_contacts_to_upsert,
    map_customers_to_company_upsert,
)
from app.features.hubspot_integration.services.hubspot_service import (
    HubSpotService,
    HubSpotServiceError,
)
from app.features.hubspot_integration.services.maconomy_service import (
    MaconomyRecordNotFoundError,
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


def _upstream_error(detail: str, exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=detail,
    )


def _batch_error_count(result: dict[str, Any]) -> int:
    payload = result.get("result", {})
    if not isinstance(payload, dict):
        return 0
    errors = payload.get("errors", [])
    return len(errors) if isinstance(errors, list) else 0


def _failed_record(
    entity_type: str,
    source_id: str,
    stage: str,
    parent_customer_number: str | None = None,
) -> list[dict[str, str]]:
    item = {
        "entity_type": entity_type,
        "source_id": source_id,
        "stage": stage,
    }
    if parent_customer_number:
        item["parent_customer_number"] = parent_customer_number
    return [item]


def _contact_mapper_skips(
    skips: list[dict[str, Any]],
) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    for item in skips:
        record = item.get("record", {})
        if not isinstance(record, dict):
            continue
        source_id = str(record.get("contactpersonnumber") or "").strip()
        if source_id:
            sanitized_item = {
                "entity_type": "contact",
                "source_id": source_id,
                "reason": str(item.get("reason") or "mapping failed"),
            }
            parent_number = str(
                record.get("contactcompanynumber") or ""
            ).strip()
            if parent_number:
                sanitized_item["parent_customer_number"] = parent_number
            sanitized.append(sanitized_item)
    return sanitized


@router.post(
    "/customers/{customer_number}/sync",
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_HUBSPOT_SYNC
            )
        )
    ],
)
async def sync_customer_by_number(
    customer_number: str,
    request: Request,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Force-sync one Maconomy Customer and all of its Contacts."""
    normalized_customer_number = customer_number.strip()
    if not normalized_customer_number:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="customer_number is required",
        )

    request_id = getattr(request.state, "request_id", uuid.uuid4())
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.UUID(str(request_id))
    run_log = await integration_run_log_service.start_run(
        session,
        request_id=request_id,
        maconomy_instance=get_settings().maconomy_shortname,
        operation="CUSTOMER_RETRY",
        trigger_type="MANUAL",
    )
    errors: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        maconomy = MaconomyService(client)
        hubspot = HubSpotService(client)

        try:
            customer = await maconomy.get_customer_with_contact_persons(
                normalized_customer_number
            )
        except MaconomyRecordNotFoundError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="MACONOMY_CUSTOMER_LOOKUP",
                error_message="Requested Customer was not found",
                failed_records=_failed_record(
                    "customer",
                    normalized_customer_number,
                    "maconomy_customer_lookup",
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except MaconomyServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="MACONOMY_CUSTOMER_LOOKUP",
                error_message="Unable to retrieve the Customer from Maconomy",
                failed_records=_failed_record(
                    "customer",
                    normalized_customer_number,
                    "maconomy_customer_lookup",
                ),
            )
            raise _upstream_error(
                "Unable to retrieve the Customer from Maconomy",
                exc,
            ) from exc

        company_payload = map_customers_to_company_upsert([customer], [])
        if not company_payload["inputs"]:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="COMPANY_MAPPING",
                error_message="Customer could not be mapped for HubSpot",
                customers_discovered=1,
                failed_records=_failed_record(
                    "customer",
                    normalized_customer_number,
                    "company_mapping",
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Customer cannot be mapped for HubSpot",
            )

        try:
            company_result = await hubspot.upsert_companies(
                {"inputs": company_payload["inputs"]}
            )
        except HubSpotServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="HUBSPOT_COMPANY_UPSERT",
                error_message="Unable to synchronize the Company with HubSpot",
                customers_discovered=1,
                failed_records=_failed_record(
                    "customer",
                    normalized_customer_number,
                    "hubspot_company_upsert",
                ),
            )
            raise _upstream_error(
                "Unable to synchronize the Company with HubSpot",
                exc,
            ) from exc

        company_ids = hubspot.index_results_by_source_id(
            company_result,
            property_name="maconomy_customer_number",
            trace_prefix="company-",
        )
        company_id = company_ids.get(normalized_customer_number)
        if not company_id:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="HUBSPOT_COMPANY_UPSERT",
                error_message="HubSpot did not confirm the Company upsert",
                customers_discovered=1,
                failed_records=_failed_record(
                    "customer",
                    normalized_customer_number,
                    "hubspot_company_upsert",
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="HubSpot did not confirm the Company upsert",
            )

        customer_checkpoint_written = False
        try:
            await maconomy.update_customer_sync_version(
                normalized_customer_number,
                customer.get("versionnumber"),
            )
            customer_checkpoint_written = True
        except MaconomyServiceError as exc:
            errors.append(
                {
                    "entity_type": "customer",
                    "source_id": normalized_customer_number,
                    "stage": "maconomy_checkpoint",
                    "message": str(exc),
                }
            )

        contacts = customer.get("contactperson", [])
        customer_name = str(customer.get("name1") or "").strip()
        parent_names = (
            {normalized_customer_number: customer_name} if customer_name else {}
        )
        enriched_contacts = enrich_contacts_with_parent_company_name(
            contacts,
            parent_names,
        )
        contact_payload = map_contacts_to_upsert(enriched_contacts)
        contacts_result: dict[str, Any] = {
            "requested": 0,
            "status": 200,
            "result": {"results": [], "errors": []},
        }
        contacts_by_number = {
            str(contact.get("contactpersonnumber") or "").strip(): contact
            for contact in contacts
            if str(contact.get("contactpersonnumber") or "").strip()
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
                customers_discovered=1,
                contacts_discovered=len(contacts),
                failed_records=[
                    *errors,
                    *[
                        {
                            "entity_type": "contact",
                            "source_id": contact_number,
                            "stage": "hubspot_contact_upsert",
                        }
                        for contact_number in contacts_by_number
                    ],
                ],
                successful_records=(
                    [
                        {
                            "entity_type": "customer",
                            "source_id": normalized_customer_number,
                            "stage": "completed",
                        }
                    ]
                    if customer_checkpoint_written
                    else []
                ),
            )
            raise _upstream_error(
                "Company synchronized, but its Contacts could not be synchronized",
                exc,
            ) from exc

        contact_ids = hubspot.index_results_by_source_id(
            contacts_result,
            property_name="maconomy_contact_person_number",
            trace_prefix="contact-",
        )
        failed_contact_ids = set(contacts_by_number) - set(contact_ids)
        errors.extend(
            {
                "entity_type": "contact",
                "source_id": contact_number,
                "stage": "hubspot_upsert",
                "message": "HubSpot did not confirm the Contact upsert",
            }
            for contact_number in sorted(failed_contact_ids)
        )

        contacts_associated = 0
        contact_checkpoint_ids: set[str] = set()
        for contact_number, contact_id in contact_ids.items():
            try:
                await hubspot.associate_contact_to_company(
                    contact_id,
                    company_id,
                )
                contacts_associated += 1
            except HubSpotServiceError as exc:
                errors.append(
                    {
                        "entity_type": "contact",
                        "source_id": contact_number,
                        "stage": "hubspot_association",
                        "message": str(exc),
                    }
                )
                continue

            contact = contacts_by_number.get(contact_number)
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

        company_batch_errors = _batch_error_count(company_result)
        contact_batch_errors = _batch_error_count(contacts_result)
        if company_batch_errors:
            errors.append(
                {
                    "entity_type": "customer",
                    "source_id": normalized_customer_number,
                    "stage": "hubspot_upsert",
                    "error_count": company_batch_errors,
                }
            )
        if contact_batch_errors:
            if not failed_contact_ids:
                errors.append(
                    {
                        "entity_type": "contact",
                        "stage": "hubspot_upsert",
                        "error_count": contact_batch_errors,
                    }
                )

        for error in errors:
            if error.get("entity_type") != "contact":
                continue
            source_id = str(error.get("source_id") or "").strip()
            contact = contacts_by_number.get(source_id)
            if contact is None:
                continue
            parent_number = str(
                contact.get("contactcompanynumber") or ""
            ).strip()
            if parent_number:
                error.setdefault("parent_customer_number", parent_number)

        successful_records = [
            *(
                [
                    {
                        "entity_type": "customer",
                        "source_id": normalized_customer_number,
                        "stage": "completed",
                        "message": (
                            "Company upsert and Maconomy writeback succeeded"
                        ),
                    }
                ]
                if customer_checkpoint_written
                else []
            ),
            *[
                {
                    "entity_type": "contact",
                    "source_id": contact_number,
                    "parent_customer_number": normalized_customer_number,
                    "stage": "completed",
                    "message": (
                        "Contact upsert, Company association, and Maconomy "
                        "writeback succeeded"
                    ),
                }
                for contact_number in contact_checkpoint_ids
            ],
        ]

        result = {
            "status": "partial_success" if errors else "success",
            "customer": {
                "source_id": normalized_customer_number,
                "hubspot_upserted": True,
                "checkpoint_written": customer_checkpoint_written,
            },
            "contacts": {
                "discovered": len(contacts),
                "requested": contacts_result.get("requested", 0),
                "upserted": len(contact_ids),
                "associated": contacts_associated,
                "checkpoints_written": len(contact_checkpoint_ids),
                "mapping_skipped": len(contact_payload["skipped"]),
            },
            "errors": errors,
        }
        await integration_run_log_service.complete_run(
            session,
            run_log,
            status=result["status"],
            customers_discovered=1,
            customers_succeeded=int(customer_checkpoint_written),
            contacts_discovered=len(contacts),
            contacts_succeeded=len(contact_checkpoint_ids),
            associations_succeeded=contacts_associated,
            checkpoints_succeeded=(
                int(customer_checkpoint_written) + len(contact_checkpoint_ids)
            ),
            skipped_count=len(contact_payload["skipped"]),
            errors=errors,
            skipped_records=_contact_mapper_skips(
                contact_payload["skipped"]
            ),
            successful_records=successful_records,
        )
        return result


@router.post(
    "/contacts/{contact_person_number}/sync",
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_HUBSPOT_SYNC
            )
        )
    ],
)
async def sync_contact_person_by_number(
    contact_person_number: str,
    request: Request,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Force-sync one Contact and associate it with its existing Company."""
    normalized_contact_number = contact_person_number.strip()
    if not normalized_contact_number:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="contact_person_number is required",
        )

    request_id = getattr(request.state, "request_id", uuid.uuid4())
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.UUID(str(request_id))
    run_log = await integration_run_log_service.start_run(
        session,
        request_id=request_id,
        maconomy_instance=get_settings().maconomy_shortname,
        operation="CONTACT_RETRY",
        trigger_type="MANUAL",
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
        maconomy = MaconomyService(client)
        hubspot = HubSpotService(client)

        try:
            contact = await maconomy.get_contact_person(
                normalized_contact_number
            )
        except MaconomyRecordNotFoundError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="MACONOMY_CONTACT_LOOKUP",
                error_message="Requested Contact Person was not found",
                failed_records=_failed_record(
                    "contact",
                    normalized_contact_number,
                    "maconomy_contact_lookup",
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except MaconomyServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="MACONOMY_CONTACT_LOOKUP",
                error_message="Unable to retrieve the Contact Person from Maconomy",
                failed_records=_failed_record(
                    "contact",
                    normalized_contact_number,
                    "maconomy_contact_lookup",
                ),
            )
            raise _upstream_error(
                "Unable to retrieve the Contact Person from Maconomy",
                exc,
            ) from exc

        customer_number = str(
            contact.get("contactcompanynumber") or ""
        ).strip()
        if not customer_number:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="CONTACT_VALIDATION",
                error_message="Contact Person has no parent Customer number",
                contacts_discovered=1,
                failed_records=_failed_record(
                    "contact",
                    normalized_contact_number,
                    "contact_validation",
                    customer_number,
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Contact Person does not have a parent Customer number",
            )

        try:
            company_ids = await hubspot.lookup_companies([customer_number])
        except HubSpotServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="HUBSPOT_COMPANY_LOOKUP",
                error_message="Unable to resolve the parent Company in HubSpot",
                contacts_discovered=1,
                failed_records=_failed_record(
                    "contact",
                    normalized_contact_number,
                    "hubspot_company_lookup",
                    customer_number,
                ),
            )
            raise _upstream_error(
                "Unable to resolve the parent Company in HubSpot",
                exc,
            ) from exc

        company_id = company_ids.get(customer_number)
        if not company_id:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="HUBSPOT_COMPANY_LOOKUP",
                error_message="Parent Company was not found in HubSpot",
                contacts_discovered=1,
                failed_records=_failed_record(
                    "contact",
                    normalized_contact_number,
                    "hubspot_company_lookup",
                    customer_number,
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent Company was not found in HubSpot",
            )

        errors: list[dict[str, Any]] = []
        try:
            parent_names = await maconomy.get_customer_names([customer_number])
        except MaconomyServiceError as exc:
            errors.append(
                {
                    "entity_type": "customer",
                    "source_id": customer_number,
                    "stage": "maconomy_customer_lookup",
                    "message": str(exc),
                }
            )
            parent_names = {}
        enriched_contacts = enrich_contacts_with_parent_company_name(
            [contact],
            parent_names,
        )
        contact_payload = map_contacts_to_upsert(enriched_contacts)
        if not contact_payload["inputs"]:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="CONTACT_MAPPING",
                error_message="Contact Person could not be mapped for HubSpot",
                contacts_discovered=1,
                failed_records=_failed_record(
                    "contact",
                    normalized_contact_number,
                    "contact_mapping",
                    customer_number,
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Contact Person cannot be mapped for HubSpot",
            )

        try:
            contact_result = await hubspot.upsert_contacts(
                {"inputs": contact_payload["inputs"]}
            )
        except HubSpotServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="HUBSPOT_CONTACT_UPSERT",
                error_message="Unable to synchronize the Contact with HubSpot",
                contacts_discovered=1,
                failed_records=_failed_record(
                    "contact",
                    normalized_contact_number,
                    "hubspot_contact_upsert",
                    customer_number,
                ),
            )
            raise _upstream_error(
                "Unable to synchronize the Contact with HubSpot",
                exc,
            ) from exc

        contact_ids = hubspot.index_results_by_source_id(
            contact_result,
            property_name="maconomy_contact_person_number",
            trace_prefix="contact-",
        )
        contact_id = contact_ids.get(normalized_contact_number)
        if not contact_id:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="HUBSPOT_CONTACT_UPSERT",
                error_message="HubSpot did not confirm the Contact upsert",
                contacts_discovered=1,
                failed_records=_failed_record(
                    "contact",
                    normalized_contact_number,
                    "hubspot_contact_upsert",
                    customer_number,
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="HubSpot did not confirm the Contact upsert",
            )

        try:
            await hubspot.associate_contact_to_company(
                contact_id,
                company_id,
            )
        except HubSpotServiceError as exc:
            await integration_run_log_service.fail_run(
                session,
                run_log,
                failure_stage="HUBSPOT_ASSOCIATION",
                error_message="Contact-to-Company association failed",
                contacts_discovered=1,
                failed_records=_failed_record(
                    "contact",
                    normalized_contact_number,
                    "hubspot_association",
                    customer_number,
                ),
            )
            raise _upstream_error(
                "Contact synchronized, but Company association failed",
                exc,
            ) from exc

        checkpoint_written = False
        try:
            await maconomy.update_contact_sync_version(
                normalized_contact_number,
                contact.get("versionnumber"),
            )
            checkpoint_written = True
        except MaconomyServiceError as exc:
            errors.append(
                {
                    "entity_type": "contact",
                    "source_id": normalized_contact_number,
                    "parent_customer_number": customer_number,
                    "stage": "maconomy_checkpoint",
                    "message": str(exc),
                }
            )

        batch_error_count = _batch_error_count(contact_result)
        if batch_error_count:
            errors.append(
                {
                    "entity_type": "contact",
                    "source_id": normalized_contact_number,
                    "parent_customer_number": customer_number,
                    "stage": "hubspot_upsert",
                    "error_count": batch_error_count,
                }
            )

        result = {
            "status": "partial_success" if errors else "success",
            "contact": {
                "source_id": normalized_contact_number,
                "parent_customer_number": customer_number,
                "hubspot_upserted": True,
                "company_associated": True,
                "checkpoint_written": checkpoint_written,
            },
            "errors": errors,
        }
        await integration_run_log_service.complete_run(
            session,
            run_log,
            status=result["status"],
            customers_discovered=0,
            customers_succeeded=0,
            contacts_discovered=1,
            contacts_succeeded=int(checkpoint_written),
            associations_succeeded=1,
            checkpoints_succeeded=int(checkpoint_written),
            skipped_count=0,
            errors=errors,
            successful_records=(
                [
                    {
                        "entity_type": "contact",
                        "source_id": normalized_contact_number,
                        "parent_customer_number": customer_number,
                        "stage": "completed",
                        "message": (
                            "Contact upsert, Company association, and Maconomy "
                            "writeback succeeded"
                        ),
                    }
                ]
                if checkpoint_written
                else []
            ),
        )
        return result
