import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.caseware_cloud_intergration.schemas import IntegrationLogRead
from app.features.caseware_cloud_intergration.services import (
    integration_log_service as service,
)

router = APIRouter(
    prefix="/cch/integration-logs",
    tags=["cch-integration-logs"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


async def _require_log(session: AsyncSession, log_id: uuid.UUID):
    integration_log = await service.get_log(session, log_id)
    if integration_log is None:
        raise HTTPException(status_code=404, detail="Integration log not found")
    return integration_log


@router.get("", response_model=list[IntegrationLogRead])
async def list_logs(
    session: DatabaseSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[IntegrationLogRead]:
    return await service.list_logs(session, offset=offset, limit=limit)


@router.get("/{log_id}", response_model=IntegrationLogRead)
async def get_log(log_id: uuid.UUID, session: DatabaseSession) -> IntegrationLogRead:
    return await _require_log(session, log_id)
