"""Paycor employee sync routes."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.features.auth.dependencies import require_api_key
from app.features.paycor_integration.services.paycor_employee_service import (
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
    response_model=list[dict[str, Any]],
)
async def get_hired_employees_today() -> list[dict[str, Any]]:
    try:
        return await PaycorService().get_hired_employees_today()

    except PaycorServiceError as exc:
        LOGGER.exception(
            "Paycor employee retrieval failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve employees from Paycor",
        ) from exc