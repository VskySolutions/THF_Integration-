"""Paycor employee sync routes."""

import logging
from typing import Any
from app.features.auth.dependencies import require_api_key

from fastapi import APIRouter, Depends, HTTPException, status

from app.features.paycor_integration.services import (
    MaconomyEmployeeService,
    MaconomyEmployeeServiceError,
    PaycorService,
    PaycorServiceError,
)


LOGGER = logging.getLogger(__name__)


router = APIRouter(
    prefix="/paycor",
    tags=["paycor-integration"],
    dependencies=[Depends(require_api_key)],
)


@router.get(
    "/hired-today",
    response_model=list[dict[str, Any]]
)
async def get_hired_employees_today() -> list[dict[str, Any]]:
    try:
        return await PaycorService().get_hired_employees_today()

    except PaycorServiceError as exc:
        LOGGER.exception(
            "Paycor invited-today retrieval failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Unable to retrieve employees "
                "invited today from Paycor"
            ),
        ) from exc

#get recent hires
@router.get(
    "/recent-hires",
    response_model=list[dict[str, Any]]
)
async def get_recent_hires() -> list[dict[str, Any]]:
    try:
        return await PaycorService().get_recent_hires()

    except PaycorServiceError as exc:
        LOGGER.exception(
            "Paycor recent-onboarding retrieval "
            "failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Unable to retrieve recently invited "
                "employees from Paycor"
            ),
        ) from exc





# ------------------------------Temporarily disabled to prevent accidental employee creation,------------------------------------------------------
# @router.post(
#     "/test-maconomy-employee",
#     response_model=dict[str, Any],
#     status_code=status.HTTP_201_CREATED,
# )
async def test_create_maconomy_employee(
    employee_data: dict[str, Any],
) -> dict[str, Any]:
    try:
        return await MaconomyEmployeeService().create_employee(
            employee_data
        )

    except MaconomyEmployeeServiceError as exc:
        LOGGER.exception(
            "Maconomy employee creation failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc