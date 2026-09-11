"""Paycor employee synchronization routes."""

import logging
import uuid
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import (
    require_api_key,
)
from app.features.integration_services import (
    IntegrationServiceIdentifier,
    require_active_integration_service,
)
from app.features.paycor_integration.services.paycor_employee_sync_service import (
    PaycorEmployeeSyncService,
    PaycorEmployeeSyncServiceError,
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


@router.post(
    "/employees/{paycor_employee_id}/sync-with-maconomy",
    response_model=dict[str, Any],
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier
                .PAYCOR_SYNC_EMPLOYEES
            )
        )
    ],
)
async def sync_employee_with_maconomy(
    paycor_employee_id: uuid.UUID,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Manually synchronize one Paycor employee."""

    try:
        return await (
            PaycorEmployeeSyncService()
            .sync_employee_by_id(
                session,
                paycor_employee_id=(
                    paycor_employee_id
                ),
            )
        )

    except PaycorEmployeeSyncServiceError as exc:
        LOGGER.exception(
            "Manual Paycor employee "
            "synchronization failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_502_BAD_GATEWAY
            ),
            detail=str(exc),
        ) from exc


@router.post(
    "/sync-recent-hires-with-maconomy",
    response_model=list[dict[str, Any]],
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier
                .PAYCOR_SYNC_EMPLOYEES
            )
        )
    ],
)
async def sync_recent_hires_with_maconomy(
    session: DatabaseSession,
) -> list[dict[str, Any]]:
    """Synchronize all eligible recent Paycor hires."""

    try:
        return await (
            PaycorEmployeeSyncService()
            .sync_recent_hires(session)
        )

    except PaycorEmployeeSyncServiceError as exc:
        LOGGER.exception(
            "Recent Paycor hire "
            "synchronization failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_502_BAD_GATEWAY
            ),
            detail=str(exc),
        ) from exc