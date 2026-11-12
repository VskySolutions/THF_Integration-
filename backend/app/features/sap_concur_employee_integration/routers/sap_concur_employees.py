from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.sap_concur_employee_integration.services import (
    MaconomyEmployeeService,
    MaconomyEmployeeServiceError,
    SAPConcurEmployeeUpdateService,
)

router = APIRouter(
    prefix="/sap-concur-employees",
    tags=["sap-concur-employee-integration"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/sync", response_model=list[dict[str, Any]])
async def sync_maconomy_employees_with_sap_concur() -> list[dict[str, Any]]:
    """Retrieve all active employees from Maconomy for SAP Concur creation."""
    try:
        return await MaconomyEmployeeService().get_all_employees()
    except MaconomyEmployeeServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to retrieve employees from Maconomy: {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - never leak upstream tracebacks
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to retrieve employees from Maconomy",
        ) from exc


@router.post("/sync-cycle", response_model=dict[str, Any])
async def run_employee_sync_cycle(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Execute complete 5-minute synchronization cycle:
    1. Fetch active employees from Maconomy.
    2. Check each employee against `employee_sync_tracking` and SAP Concur.
    3. Perform creation, version-controlled update, adoption, or skip.
    4. Log every action and error into `employee_sync_log`.
    """
    try:
        employees = await MaconomyEmployeeService().get_all_employees()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch employees from Maconomy: {exc}",
        ) from exc

    update_service = SAPConcurEmployeeUpdateService(db=db)

    stats: dict[str, Any] = {
        "total_fetched": len(employees),
        "created": 0,
        "updated": 0,
        "adopted_and_updated": 0,
        "skipped": 0,
        "failed": 0,
        "results": [],
    }

    for emp in employees:
        try:
            res = await update_service.sync_or_update_employee(emp)
            action = res.get("action")
            if action == "CREATED":
                stats["created"] += 1
            elif action == "UPDATED":
                stats["updated"] += 1
            elif action == "ADOPT_AND_UPDATED":
                stats["adopted_and_updated"] += 1
            elif action == "SKIPPED":
                stats["skipped"] += 1
            elif "FAILED" in str(action):
                stats["failed"] += 1
            stats["results"].append(res)
        except Exception as exc:
            stats["failed"] += 1
            stats["results"].append({
                "employee_number": emp.get("employeenumber"),
                "status": "ERROR",
                "error": str(exc),
            })

    return stats
