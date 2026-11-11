from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.features.auth.dependencies import require_api_key
from app.features.sap_concur_employee_integration.services import (
    MaconomyEmployeeService,
    MaconomyEmployeeServiceError,
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
