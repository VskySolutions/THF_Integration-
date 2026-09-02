import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.cch_axcess_integration.models import (
    CCHAxcessEntityEngagementMapping,
)


async def create_mapping(
    session: AsyncSession,
    caseware_cwid: str,
    job_number: str,
    maconomy_job_version_number: str,
) -> CCHAxcessEntityEngagementMapping:
    mapping = CCHAxcessEntityEngagementMapping(
        caseware_cloud_entity_cwid=caseware_cwid,
        maconomy_job_number=job_number,
        maconomy_job_version_number=maconomy_job_version_number,
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return mapping


async def set_mapping_addresses(
    session: AsyncSession,
    mapping: CCHAxcessEntityEngagementMapping,
    address_ids: list[dict[str, str]],
) -> CCHAxcessEntityEngagementMapping:
    mapping.cw_addresses = address_ids
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


async def update_engagement_sync_snapshot(
    session: AsyncSession,
    mapping: CCHAxcessEntityEngagementMapping,
    version_number: int,
    address_mapping: dict[str, str],
) -> CCHAxcessEntityEngagementMapping:
    mapping.maconomy_job_version_number = str(version_number)
    mapping.cw_addresses = [address_mapping]
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
