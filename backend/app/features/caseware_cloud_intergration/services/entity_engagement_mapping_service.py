import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.caseware_cloud_intergration.models import (
    CasewareCloudEntityEngagementMapping,
)


async def list_mappings(
    session: AsyncSession, *, offset: int, limit: int
) -> list[CasewareCloudEntityEngagementMapping]:
    statement = (
        select(CasewareCloudEntityEngagementMapping)
        .order_by(CasewareCloudEntityEngagementMapping.created_on_utc.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.scalars(statement)
    return list(result)


async def get_mapping(
    session: AsyncSession, mapping_id: uuid.UUID
) -> CasewareCloudEntityEngagementMapping | None:
    return await session.get(CasewareCloudEntityEngagementMapping, mapping_id)
