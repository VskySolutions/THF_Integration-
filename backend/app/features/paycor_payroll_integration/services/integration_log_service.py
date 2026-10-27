"""Database operations for Paycor Payroll integration logs."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.paycor_payroll_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)
from app.features.paycor_payroll_integration.models.integration_log import (
    PaycorPayrollIntegrationLog,
)


async def create_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    planner_id: str | None,
    legal_entity_id: int,
    status: IntegrationStatus,
    action: IntegrationAction,
    message: str | None,
) -> PaycorPayrollIntegrationLog:
    settings = get_settings()

    integration_log = PaycorPayrollIntegrationLog(
        paycor_payroll_journal_mapping_log_id=mapping_id,
        paycor_planner_id=planner_id,
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
) -> list[PaycorPayrollIntegrationLog]:
    statement = (
        select(PaycorPayrollIntegrationLog)
        .order_by(
            PaycorPayrollIntegrationLog.created_on_utc.desc()
        )
        .offset(offset)
        .limit(limit)
    )

    result = await session.scalars(statement)

    return list(result)


async def get_log(
    session: AsyncSession,
    log_id: uuid.UUID,
) -> PaycorPayrollIntegrationLog | None:
    return await session.get(
        PaycorPayrollIntegrationLog,
        log_id,
    )
