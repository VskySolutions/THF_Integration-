import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.cch_axcess_integration.models import (
    CCHAxcessEntityEngagementMapping,
)


async def create_mapping(
    session: AsyncSession,
    cch_client_id: str,
    job_number: str,
    maconomy_job_version_number: str,
) -> CCHAxcessEntityEngagementMapping:
    mapping = CCHAxcessEntityEngagementMapping(
        cch_axcess_entity_cchid=cch_client_id,
        maconomy_job_number=job_number,
        maconomy_job_version_number=maconomy_job_version_number,
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return mapping


async def update_job_version_number(
    session: AsyncSession,
    mapping: CCHAxcessEntityEngagementMapping,
    version_number: int,
) -> CCHAxcessEntityEngagementMapping:
    mapping.maconomy_job_version_number = str(version_number)
    await session.commit()
    await session.refresh(mapping)
    return mapping


async def list_mappings(
    session: AsyncSession, *, offset: int, limit: int
) -> list[CCHAxcessEntityEngagementMapping]:
    statement = (
        select(CCHAxcessEntityEngagementMapping)
        .order_by(CCHAxcessEntityEngagementMapping.created_on_utc.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.scalars(statement)
    return list(result)


async def get_mapping(
    session: AsyncSession, mapping_id: uuid.UUID
) -> CCHAxcessEntityEngagementMapping | None:
    return await session.get(CCHAxcessEntityEngagementMapping, mapping_id)


async def get_mapping_by_job_number(
    session: AsyncSession, job_number: str
) -> CCHAxcessEntityEngagementMapping | None:
    statement = select(CCHAxcessEntityEngagementMapping).where(
        CCHAxcessEntityEngagementMapping.maconomy_job_number == job_number
    )
    return await session.scalar(statement)
