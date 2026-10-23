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


PaycorPayrollServiceDependency = Annotated[
    PaycorPayrollService,
    Depends(get_paycor_payroll_service),
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
