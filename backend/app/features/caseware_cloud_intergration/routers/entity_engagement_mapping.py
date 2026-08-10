import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.caseware_cloud_intergration.schemas import (
    EntityEngagementMappingRead,
)
from app.features.caseware_cloud_intergration.services import (
    entity_engagement_mapping_service as service,
)

router = APIRouter(
    prefix="/caseware-cloud/entity-engagement-mappings",
    tags=["caseware-cloud-mappings"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


async def _require_mapping(session: AsyncSession, mapping_id: uuid.UUID):
    mapping = await service.get_mapping(session, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return mapping


@router.get("", response_model=list[EntityEngagementMappingRead])
async def list_mappings(
    session: DatabaseSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[EntityEngagementMappingRead]:
    return await service.list_mappings(session, offset=offset, limit=limit)


@router.get("/{mapping_id}", response_model=EntityEngagementMappingRead)
async def get_mapping(
    mapping_id: uuid.UUID, session: DatabaseSession
) -> EntityEngagementMappingRead:
    return await _require_mapping(session, mapping_id)
