import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.caseware_cloud_intergration.models import (
    CasewareCloudEntityEngagementMapping,
)


async def create_mapping(
    session: AsyncSession,
    caseware_cwid: str,
    job_number: str,
    maconomy_job_version_number: str,
) -> CasewareCloudEntityEngagementMapping:
    mapping = CasewareCloudEntityEngagementMapping(
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
    mapping: CasewareCloudEntityEngagementMapping,
    address_ids: list[dict[str, str]],
) -> CasewareCloudEntityEngagementMapping:
    mapping.cw_addresses = address_ids
    await session.commit()
    await session.refresh(mapping)
    return mapping


async def update_job_version_number(
    session: AsyncSession,
    mapping: CasewareCloudEntityEngagementMapping,
    version_number: int,
) -> CasewareCloudEntityEngagementMapping:
    mapping.maconomy_job_version_number = str(version_number)
    await session.commit()
    await session.refresh(mapping)
    return mapping


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


async def get_mapping_by_job_number(
    session: AsyncSession, job_number: str
) -> CasewareCloudEntityEngagementMapping | None:
    statement = select(CasewareCloudEntityEngagementMapping).where(
        CasewareCloudEntityEngagementMapping.maconomy_job_number == job_number
    )
    return await session.scalar(statement)
