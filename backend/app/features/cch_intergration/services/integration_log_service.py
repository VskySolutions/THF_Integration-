import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.caseware_cloud_intergration.constants import (
    IntegrationAction,
    IntegrationStatus,
)
from app.features.caseware_cloud_intergration.models import CasewareCloudIntegrationLog


async def create_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    job_number: str,
    status: IntegrationStatus,
    action: IntegrationAction,
    message: str,
) -> CasewareCloudIntegrationLog:
    settings = get_settings()
    integration_log = CasewareCloudIntegrationLog(
        caseware_cloud_entity_engagement_mapping_id=mapping_id,
        instance=settings.maconomy_shortname,
        base_url=settings.maconomy_url,
        username=settings.maconomy_username,
        status=status,
        message=message,
        action=action,
        jobnumber=job_number,
    )
    session.add(integration_log)
    await session.commit()
    await session.refresh(integration_log)
    return integration_log


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
