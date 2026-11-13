import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.sap_concur_engagements_and_tasks_integration.models.integration_log import (
    EngagementTaskIntegrationAction,
    EngagementTaskIntegrationStatus,
    SAPConcurEngagementTaskIntegrationLog,
)


async def create_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    maconomy_jobnumber: str,
    maconomy_tasknumber: str,
    status: EngagementTaskIntegrationStatus,
    action: EngagementTaskIntegrationAction,
    message: str,
) -> SAPConcurEngagementTaskIntegrationLog:
    settings = get_settings()
    integration_log = SAPConcurEngagementTaskIntegrationLog(
        sap_concur_engagement_task_mapping_id=mapping_id,
        maconomy_jobnumber=maconomy_jobnumber,
        maconomy_tasknumber=maconomy_tasknumber,
        instance=settings.maconomy_shortname,
        base_url=settings.maconomy_url,
        username=settings.maconomy_username,
        status=status,
        action=action,
        message=message[:1000],
    )
    session.add(integration_log)
    await session.commit()
    await session.refresh(integration_log)
    return integration_log
