"""Paycor employee synchronization routes."""

import logging
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Query
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
# from app.features.integration_services import (
#     #IntegrationServiceIdentifier,
#     #require_active_integration_service,
# )
from app.features.paycor_integration.services.paycor_employee_service import (
    PaycorService,
    PaycorServiceError,
)
from app.features.paycor_integration.services.paycor_employee_sync_service import (
    PaycorEmployeeSyncService,
    #PaycorEmployeeSyncServiceError,
)


LOGGER = logging.getLogger(__name__)


router = APIRouter(
    prefix="/paycor",
    tags=["paycor-integration"],
    dependencies=[Depends(require_api_key)],
)


DatabaseSession = Annotated[
    AsyncSession,
    Depends(get_db),
]


@router.get(
    "/hired-today",
    response_model=list[dict[str, Any]],
)
async def get_hired_employees_today(
) -> list[dict[str, Any]]:
    try:
        return await (
            PaycorService()
            .get_hired_employees_today()
        )

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


@router.get(
    "/recent-hires",
    response_model=list[dict[str, Any]],
)
async def get_recent_hires(
) -> list[dict[str, Any]]:
    try:
        return await (
            PaycorService().get_recent_hires()
        )

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





@router.post("/sync-onboarding-employees-with-maconomy")
async def sync_onboarding_employees_with_maconomy(
    max_records: int = Query(
        default=2,
        ge=1,
        le=3,
        description="Temporary testing limit",
    ),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    sync_service = PaycorEmployeeSyncService()

    return await sync_service.sync_onboarding_employees(
        session,
        max_records=max_records,
    )