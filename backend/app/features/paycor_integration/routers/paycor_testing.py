"""Read-only routes for testing the Paycor integration."""

import logging
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.features.auth.dependencies import (
    require_api_key,
)
from app.features.paycor_integration.services.maconomy_employee_service import (
    MaconomyEmployeeService,
    MaconomyEmployeeServiceError,
)
from app.features.paycor_integration.services.paycor_employee_service import (
    PaycorService,
    PaycorServiceError,
)


LOGGER = logging.getLogger(__name__)


router = APIRouter(
    prefix="/paycor/testing",
    tags=["testing-integration"],
    dependencies=[Depends(require_api_key)],
)


@router.get(
    "/recent-hires",
    response_model=list[dict[str, Any]],
)
async def get_recent_hires(
) -> list[dict[str, Any]]:
    """Preview employees eligible for recent-hire sync."""

    try:
        return await (
            PaycorService().get_recent_hires()
        )

    except PaycorServiceError as exc:
        LOGGER.exception(
            "Paycor recent-hire "
            "retrieval failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_502_BAD_GATEWAY
            ),
            detail=(
                "Unable to retrieve recent "
                "hires from Paycor"
            ),
        ) from exc


@router.get(
    "/employees/{paycor_employee_id}/preview",
    response_model=dict[str, Any],
)
async def preview_paycor_employee(
    paycor_employee_id: uuid.UUID,
) -> dict[str, Any]:
    """Preview one normalized Paycor employee."""

    try:
        employee = await (
            PaycorService().get_employee_by_id(
                str(paycor_employee_id)
            )
        )

    except PaycorServiceError as exc:
        LOGGER.exception(
            "Paycor employee preview failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_502_BAD_GATEWAY
            ),
            detail=str(exc),
        ) from exc

    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paycor employee was not found",
        )

    return employee


@router.get(
    "/maconomy/employees/{employee_number}/exists",
    response_model=dict[str, Any],
)
async def check_maconomy_employee_exists(
    employee_number: str,
) -> dict[str, Any]:
    """Check whether an employee exists in Maconomy."""

    normalized_employee_number = (
        employee_number.strip()
    )

    if not normalized_employee_number:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail="Employee number is required",
        )

    try:
        employee_numbers = await (
            MaconomyEmployeeService()
            .get_all_employee_numbers()
        )

    except MaconomyEmployeeServiceError as exc:
        LOGGER.exception(
            "Maconomy employee lookup failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_502_BAD_GATEWAY
            ),
            detail=str(exc),
        ) from exc

    return {
        "employeeNumber": (
            normalized_employee_number
        ),
        "exists": (
            normalized_employee_number
            in employee_numbers
        ),
        "totalMaconomyEmployees": len(
            employee_numbers
        ),
    }