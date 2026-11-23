import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.sap_concur_invoice_integration_v2.constants import (
    IntegrationAction,
    IntegrationStatus,
    ProcessingStage,
)
from app.features.sap_concur_invoice_integration_v2.models import (
    SAPConcurInvoiceIntegrationLogV2,
)


async def create_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    invoice_id: str,
    status: IntegrationStatus,
    message: str,
    processing_stage: ProcessingStage,
    details: dict[str, Any],
    action: IntegrationAction = IntegrationAction.CREATE,
) -> None:
    settings = get_settings()
    session.add(
        SAPConcurInvoiceIntegrationLogV2(
            sap_concur_invoice_mapping_id=mapping_id,
            instance=settings.maconomy_shortname,
            base_url=settings.maconomy_url,
            username=settings.maconomy_username,
            status=status,
            message=message,
            processing_stage=processing_stage.value,
            details=details,
            action=action,
            invoice_id=invoice_id,
        )
    )
    await session.commit()
