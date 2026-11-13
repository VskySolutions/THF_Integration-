import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.sap_concur_invoice_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
    ProcessingStage,
)
from app.features.sap_concur_invoice_integration.models.integration_log import (
    SAPConcurInvoiceIntegrationLog,
)


async def create_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    invoice_id: str,
    status: IntegrationStatus,
    action: IntegrationAction,
    message: str,
    processing_stage: ProcessingStage | None = None,
    details: dict | None = None,
) -> SAPConcurInvoiceIntegrationLog:
    settings = get_settings()
    integration_log = SAPConcurInvoiceIntegrationLog(
        sap_concur_invoice_mapping_id=mapping_id,
        instance=settings.maconomy_shortname,
        base_url=settings.maconomy_url,
        username=settings.maconomy_username,
        status=status,
        message=message,
        processing_stage=processing_stage.value if processing_stage else None,
        details=details,
        action=action,
        invoice_id=invoice_id,
    )
    session.add(integration_log)
    await session.commit()
    await session.refresh(integration_log)
    return integration_log


async def list_logs(
    session: AsyncSession, *, offset: int, limit: int
) -> list[SAPConcurInvoiceIntegrationLog]:
    statement = (
        select(SAPConcurInvoiceIntegrationLog)
        .order_by(SAPConcurInvoiceIntegrationLog.created_on_utc.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.scalars(statement)
    return list(result)


async def get_log(
    session: AsyncSession, log_id: uuid.UUID
) -> SAPConcurInvoiceIntegrationLog | None:
    return await session.get(SAPConcurInvoiceIntegrationLog, log_id)
