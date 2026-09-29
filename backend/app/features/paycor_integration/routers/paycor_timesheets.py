"""Maconomy-to-Paycor timesheet routes."""

import logging
from collections.abc import AsyncIterator
from datetime import date
from typing import Annotated, Any

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from app.core.config import get_settings
from app.features.auth.dependencies import (
    require_api_key,
)
from app.features.paycor_integration.services.maconomy_timesheet_service import (MaconomyTimesheetService,MaconomyTimesheetServiceError)



LOGGER = logging.getLogger(__name__)


router = APIRouter(
    prefix="/paycor/timesheets",
    tags=["paycor-timesheet-integration"],
    dependencies=[Depends(require_api_key)],
)


async def get_maconomy_service(
) -> AsyncIterator[MaconomyTimesheetService]:
    """Provide a Maconomy service and HTTP client."""

    async with httpx.AsyncClient(
        timeout=60.0
    ) as client:
        yield MaconomyTimesheetService(
            client=client,
            settings=get_settings(),
        )


MaconomyServiceDependency = Annotated[
    MaconomyTimesheetService,
    Depends(get_maconomy_service),
]


@router.get(
    "/approved",
    response_model=dict[str, Any],
)
async def get_approved_timesheet_lines(
    period_start_from: date = Query(...),
    period_start_to: date = Query(...),
) -> dict[str, Any]:
    """Retrieve approved Maconomy timesheets."""

    if period_start_to < period_start_from:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=(
                "period_start_to must be on or "
                "after period_start_from"
            ),
        )

    settings = get_settings()

    try:
        async with httpx.AsyncClient(
            timeout=60.0
        ) as client:
            service = MaconomyTimesheetService(
                client=client,
                settings=settings,
            )

            records = await (
                service
                .get_approved_timesheet_lines(
                    period_start_from=(
                        period_start_from
                    ),
                    period_start_to=(
                        period_start_to
                    ),
                )
            )

    except MaconomyTimesheetServiceError as exc:
        LOGGER.exception(
            "Approved Maconomy timesheet "
            "retrieval failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_502_BAD_GATEWAY
            ),
            detail=str(exc),
        ) from exc

    return {
        "periodStartFrom": (
            period_start_from.isoformat()
        ),
        "periodStartTo": (
            period_start_to.isoformat()
        ),
        "totalRecords": len(records),
        "records": records,
    }