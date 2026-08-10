import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.caseware_cloud_intergration.models import CasewareCloudIntegrationLog


async def list_logs(
    session: AsyncSession, *, offset: int, limit: int
) -> list[CasewareCloudIntegrationLog]:
    statement = (
        select(CasewareCloudIntegrationLog)
        .order_by(CasewareCloudIntegrationLog.created_on_utc.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.scalars(statement)
    return list(result)


async def get_log(
    session: AsyncSession, log_id: uuid.UUID
) -> CasewareCloudIntegrationLog | None:
    return await session.get(CasewareCloudIntegrationLog, log_id)
