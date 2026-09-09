"""Database operations for Paycor integration logs."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.paycor_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)
from app.features.paycor_integration.models.integration_log import (
    PaycorIntegrationLog,
)


async def create_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    onboarding_employee_id: uuid.UUID,
    legal_entity_id: int,
    status: IntegrationStatus,
    action: IntegrationAction,
    message: str,
) -> PaycorIntegrationLog:
    settings = get_settings()

    integration_log = PaycorIntegrationLog(
        paycor_employee_mapping_log_id=mapping_id,
        paycor_onboarding_employee_id=onboarding_employee_id,
        instance=str(legal_entity_id),
        base_url=settings.paycor_url,
        status=status,
        message=message,
        action=action,
    )

    session.add(integration_log)

    await session.commit()
    await session.refresh(integration_log)

    return integration_log


async def list_logs(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
) -> list[PaycorIntegrationLog]:
    statement = (
        select(PaycorIntegrationLog)
        .order_by(PaycorIntegrationLog.created_on_utc.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await session.scalars(statement)
    return list(result)


async def get_log(
    session: AsyncSession,
    log_id: uuid.UUID,
) -> PaycorIntegrationLog | None:
    return await session.get(PaycorIntegrationLog, log_id)