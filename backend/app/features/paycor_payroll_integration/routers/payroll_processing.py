"""Routes for Paycor Payroll Processing."""

import logging
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import Settings, get_settings
from app.features.auth.dependencies import require_api_key
from app.features.paycor_payroll_integration.constants import (
    PAYCOR_PAYROLL_ROUTER_PREFIX,
    PAYCOR_PAYROLL_TAG,
)
from app.features.paycor_payroll_integration.mappers.payroll_journal_mapper import (
    map_paycor_gl_record_to_maconomy_line,
    map_paycor_gl_to_maconomy_card,
)
from app.features.paycor_payroll_integration.services.maconomy_general_journal_service import (
    MaconomyGeneralJournalService,
    MaconomyGeneralJournalServiceError,
)
from app.features.paycor_payroll_integration.services.paycor_payroll_service import (
    PaycorPayrollService,
    PaycorPayrollServiceError,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix=PAYCOR_PAYROLL_ROUTER_PREFIX,
    tags=[PAYCOR_PAYROLL_TAG],
    dependencies=[Depends(require_api_key)],
)


def get_paycor_payroll_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PaycorPayrollService:
    """Dependency provider for PaycorPayrollService."""
    return PaycorPayrollService(settings=settings)


def get_maconomy_journal_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> MaconomyGeneralJournalService:
    """Dependency provider for MaconomyGeneralJournalService."""
    return MaconomyGeneralJournalService(settings=settings)


PaycorPayrollServiceDependency = Annotated[
    PaycorPayrollService,
    Depends(get_paycor_payroll_service),
]
MaconomyJournalServiceDependency = Annotated[
    MaconomyGeneralJournalService,
    Depends(get_maconomy_journal_service),
]


@router.get(
    "/payroll-processing/{legal_entity_id}",
    response_model=dict[str, Any],
    summary="Get Paycor Payroll Processing Data and General Ledger Entries",
)
async def get_payroll_processing(
    legal_entity_id: int,
    from_check_date: str | None = Query(
        default=None,
        alias="fromCheckDate",
        description="Filter from check date in format: YYYY-MM-DDTHH:MM:SS. Defaults dynamically to today's date if omitted.",
    ),
    to_check_date: str | None = Query(
        default=None,
        alias="toCheckDate",
        description="Optional filter to check date in format: YYYY-MM-DDTHH:MM:SS",
    ),
    include_other_payruns: str = Query(
        default="All",
        alias="includeOtherPayruns",
        description="Options: 'All', 'A' = Additional Payruns, 'J' = Adjustment Payrun",
    ),
    continuation_token: str | None = Query(default=None, alias="continuationToken"),
    payroll_service: PaycorPayrollService = Depends(get_paycor_payroll_service),
) -> dict[str, Any]:
    """
    Retrieve payroll processing records, extract plannerIds, groupIds, and runTypes into a variable,
    and iterate through each plannerId to fetch the General Ledger with Employee data.
    """
    try:
        # 1. Fetch payroll processing response
        payroll_processing_result = await payroll_service.get_payroll_processing(
            legal_entity_id=legal_entity_id,
            from_check_date=from_check_date,
            to_check_date=to_check_date,
            include_other_payruns=include_other_payruns,
            continuation_token=continuation_token,
        )

        records = (
            payroll_processing_result.get("records", [])
            if isinstance(payroll_processing_result, dict)
            else []
        )

        # 2. Store only unique plannerId, groupId, and runType in a variable
        payruns_summary: list[dict[str, Any]] = []
        seen_planners: set[str] = set()

        for record in records:
            raw_planner_id = (
                record.get("plannerId")
                or record.get("plannerID")
                or record.get("id")
            )
            if not raw_planner_id:
                continue

            planner_id = str(raw_planner_id).strip()
            if planner_id in seen_planners:
                continue
            seen_planners.add(planner_id)

            group_id = record.get("groupId") or record.get("groupID")
            run_type = record.get("runType") or record.get("runtype")

            payruns_summary.append({
                "plannerId": planner_id,
                "groupId": group_id,
                "runType": run_type,
            })

        # 3. Loop over the variable list, fetching GL data and structuring by plannerId
        general_ledger_by_planner_id: dict[str, Any] = {}
        for item in payruns_summary:
            current_planner_id = item["plannerId"]

            gl_data = await payroll_service.get_general_ledger_with_employee(
                legal_entity_id=legal_entity_id,
                planner_id=current_planner_id,
            )

            # Store plannedId-wise object ready for subsequent journal & lines creation
            general_ledger_by_planner_id[current_planner_id] = {
                "plannerId": current_planner_id,
                "groupId": item.get("groupId"),
                "runType": item.get("runType"),
                "records": (
                    gl_data.get("records", [])
                    if isinstance(gl_data, dict) and "records" in gl_data
                    else gl_data
                ),
            }

        return {
            "legalEntityId": legal_entity_id,
            "payrunsSummary": payruns_summary,
            "generalLedgerByPlannerId": general_ledger_by_planner_id,
        }

    except PaycorPayrollServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        )
    except Exception as exc:
        LOGGER.exception("Unexpected error in get_payroll_processing: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        )


@router.get(
    "/general-ledger-with-employee/{legal_entity_id}",
    response_model=dict[str, Any],
    summary="Get Paycor General Ledger with Employee by Planner ID",
)
async def get_general_ledger_with_employee(
    legal_entity_id: int,
    planner_id: str = Query(..., alias="plannerId", description="Paycor Planner ID"),
    continuation_token: str | None = Query(default=None, alias="continuationToken"),
    payroll_service: PaycorPayrollService = Depends(get_paycor_payroll_service),
) -> dict[str, Any]:
    """Direct endpoint to fetch general ledger with employee data for a given plannerId."""
    try:
        return await payroll_service.get_general_ledger_with_employee(
            legal_entity_id=legal_entity_id,
            planner_id=planner_id,
            continuation_token=continuation_token,
        )
    except PaycorPayrollServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        )
    except Exception as exc:
        LOGGER.exception("Unexpected error in get_general_ledger_with_employee: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        )


@router.post(
    "/create-journal-for-planner/{legal_entity_id}/{planner_id}",
    response_model=dict[str, Any],
    summary="Create a Maconomy General Journal for a specific Paycor Planner ID",
)
async def create_journal_for_planner(
    legal_entity_id: int,
    planner_id: str,
    group_id: str | None = Query(default=None, alias="groupId"),
    run_type: str | None = Query(default=None, alias="runType"),
    company_number: str = Query(default="100", alias="companyNumber"),
    transaction_date: str | None = Query(default=None, alias="transactionDate"),
    description: str | None = Query(default=None),
    payroll_service: PaycorPayrollService = Depends(get_paycor_payroll_service),
    maconomy_service: MaconomyGeneralJournalService = Depends(get_maconomy_journal_service),
) -> dict[str, Any]:
    """
    Fetch Paycor General Ledger data for a single planner ID,
    map it to Maconomy card and line items, and create the General Journal entry.
    """
    try:
        # 1. Fetch GL data from Paycor
        gl_response = await payroll_service.get_general_ledger_with_employee(
            legal_entity_id=legal_entity_id,
            planner_id=planner_id,
        )

        records: list[dict[str, Any]] = (
            gl_response.get("records", [])
            if isinstance(gl_response, dict) and "records" in gl_response
            else gl_response
            if isinstance(gl_response, list)
            else []
        )

        if not records:
            return {
                "plannerId": planner_id,
                "status": "SKIPPED",
                "message": f"No GL records found for planner {planner_id}",
            }

        # 2. Map header card & table lines
        card_data = map_paycor_gl_to_maconomy_card(
            planner_id=planner_id,
            group_id=group_id,
            run_type=run_type,
            company_number=company_number,
            transaction_date=transaction_date,
            description=description,
        )
        lines = [map_paycor_gl_record_to_maconomy_line(r) for r in records]

        # 3. Create General Journal in Maconomy
        creation_result = await maconomy_service.create_journal_with_lines(
            card_data=card_data,
            lines=lines,
        )

        return {
            "status": "SUCCESS",
            "legalEntityId": legal_entity_id,
            "plannerId": planner_id,
            "maconomy": creation_result,
        }

    except (PaycorPayrollServiceError, MaconomyGeneralJournalServiceError) as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        )
    except Exception as exc:
        LOGGER.exception("Error in create_journal_for_planner: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        )


@router.post(
    "/sync-payroll-to-maconomy",
    response_model=dict[str, Any],
    summary="Fetch all Payruns from Paycor (Legal Entity 158797) and sync each into Maconomy General Journals",
)
async def sync_payroll_to_maconomy(
    company_number: str = Query(default="100", alias="companyNumber"),
    from_check_date: str | None = Query(
        default=None,
        alias="fromCheckDate",
        description="Filter from check date in format: YYYY-MM-DDTHH:MM:SS. Defaults to today if omitted.",
    ),
    to_check_date: str | None = Query(
        default=None,
        alias="toCheckDate",
        description="Optional filter to check date in format: YYYY-MM-DDTHH:MM:SS",
    ),
    include_other_payruns: str = Query(
        default="All",
        alias="includeOtherPayruns",
    ),
    payroll_service: PaycorPayrollService = Depends(get_paycor_payroll_service),
    maconomy_service: MaconomyGeneralJournalService = Depends(get_maconomy_journal_service),
) -> dict[str, Any]:
    """
    End-to-end sync using fixed Legal Entity 158797:
    1. Retrieve payroll processing payruns for legal entity 158797.
    2. Extract unique plannerIds.
    3. For each plannerId, fetch GL records, map to Maconomy format, and create journal.
    4. Return aggregated synchronization report.
    """
    legal_entity_id = 158797
    try:
        # 1. Fetch processing payruns
        payroll_processing_result = await payroll_service.get_payroll_processing(
            legal_entity_id=legal_entity_id,
            from_check_date=from_check_date,
            to_check_date=to_check_date,
            include_other_payruns=include_other_payruns,
        )

        records = (
            payroll_processing_result.get("records", [])
            if isinstance(payroll_processing_result, dict)
            else []
        )

        seen_planners: set[str] = set()
        journals_created: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for record in records:
            raw_planner_id = (
                record.get("plannerId")
                or record.get("plannerID")
                or record.get("id")
            )
            if not raw_planner_id:
                continue

            planner_id = str(raw_planner_id).strip()
            if planner_id in seen_planners:
                continue
            seen_planners.add(planner_id)

            group_id = record.get("groupId") or record.get("groupID")
            run_type = record.get("runType") or record.get("runtype")

            try:
                gl_data = await payroll_service.get_general_ledger_with_employee(
                    legal_entity_id=legal_entity_id,
                    planner_id=planner_id,
                )
                gl_records = (
                    gl_data.get("records", [])
                    if isinstance(gl_data, dict) and "records" in gl_data
                    else gl_data
                    if isinstance(gl_data, list)
                    else []
                )

                if not gl_records:
                    journals_created.append({
                        "plannerId": planner_id,
                        "status": "SKIPPED",
                        "message": "No GL records found",
                    })
                    continue

                card_data = map_paycor_gl_to_maconomy_card(
                    planner_id=planner_id,
                    group_id=group_id,
                    run_type=run_type,
                    company_number=company_number,
                )
                lines = [map_paycor_gl_record_to_maconomy_line(r) for r in gl_records]

                creation_res = await maconomy_service.create_journal_with_lines(
                    card_data=card_data,
                    lines=lines,
                )

                journals_created.append({
                    "plannerId": planner_id,
                    "groupId": group_id,
                    "runType": run_type,
                    "status": "SUCCESS",
                    "maconomy": creation_res,
                })

            except Exception as line_err:
                LOGGER.error(
                    "Failed to create journal for planner %s: %s",
                    planner_id,
                    line_err,
                )
                errors.append({
                    "plannerId": planner_id,
                    "error": str(line_err),
                })

        return {
            "legalEntityId": legal_entity_id,
            "totalPayrunsFound": len(seen_planners),
            "createdJournals": journals_created,
            "errors": errors,
        }

    except PaycorPayrollServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        )
    except Exception as exc:
        LOGGER.exception("Unexpected error in sync_payroll_to_maconomy: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        )

