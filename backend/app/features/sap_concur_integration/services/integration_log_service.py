import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.sap_concur_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)

from app.features.sap_concur_integration.models.integration_log import SAPConcurIntegrationLog


async def create_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    # job_number: str,
    expensesheet_number: str,
    status: IntegrationStatus,
    action: IntegrationAction,
    message: str,
) -> SAPConcurIntegrationLog:
    settings = get_settings()
    integration_log = SAPConcurIntegrationLog(
        sap_concur_expensesheet_expensereport_mapping_id=mapping_id,
        instance=settings.maconomy_shortname,
        base_url=settings.maconomy_url,
        username=settings.maconomy_username,
        status=status,
        message=message,
        action=action,
        # jobnumber=job_number,
        expensesheet_number=expensesheet_number,
    )
    session.add(integration_log)
    await session.commit()
    await session.refresh(integration_log)
    return integration_log


async def list_logs(
    session: AsyncSession, *, offset: int, limit: int
) -> list[SAPConcurIntegrationLog]:
    statement = (
        select(SAPConcurIntegrationLog)
        .order_by(SAPConcurIntegrationLog.created_on_utc.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.scalars(statement)
    return list(result)


async def get_log(
    session: AsyncSession, log_id: uuid.UUID
) -> SAPConcurIntegrationLog | None:
    return await session.get(SAPConcurIntegrationLog, log_id)
