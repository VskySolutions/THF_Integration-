"""Paycor employee update routes."""

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
    tags=["paycor-integration-update"],
    dependencies=[Depends(require_api_key)],
)


DatabaseSession = Annotated[
    AsyncSession,
    Depends(get_db),
]


@router.post(
    "/employees/{paycor_employee_id}"
    "/update-with-maconomy",
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
async def update_employee_with_maconomy(
    paycor_employee_id: uuid.UUID,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Update one Maconomy employee using Paycor data."""

    try:
        return await (
            PaycorEmployeeSyncService()
            .update_employee_by_id(
                session,
                paycor_employee_id=(
                    paycor_employee_id
                ),
            )
        )

    except PaycorEmployeeSyncServiceError as exc:
        LOGGER.exception(
            "Manual Paycor employee update failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post(
    "/sync-updated-employees-with-maconomy",
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
async def sync_updated_employees_with_maconomy(
    session: DatabaseSession,
) -> dict[str, Any]:
    """Update all eligible mapped Maconomy employees."""

    try:
        return await (
            PaycorEmployeeSyncService()
            .sync_updated_employees(
                session
            )
        )

    except PaycorEmployeeSyncServiceError as exc:
        LOGGER.exception(
            "Automatic Paycor employee update "
            "synchronization failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc