import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.sap_concur_vendor_integration.models.integration_log import (
    SAPConcurVendorIntegrationLog,
    VendorIntegrationAction,
    VendorIntegrationStatus,
)


async def create_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    sap_concur_vendor_code: str | None,
    maconomy_vendor_code: str | None,
    status: VendorIntegrationStatus,
    action: VendorIntegrationAction,
    message: str,
) -> SAPConcurVendorIntegrationLog:
    settings = get_settings()
    integration_log = SAPConcurVendorIntegrationLog(
        sap_concur_vendor_mapping_id=mapping_id,
        sap_concur_vendor_code=sap_concur_vendor_code,
        maconomy_vendor_code=maconomy_vendor_code,
        instance=settings.maconomy_shortname,
        base_url=settings.maconomy_url,
        username=settings.maconomy_username,
        status=status,
        message=message[:1000],
        action=action,
    )
    session.add(integration_log)
    await session.commit()
    await session.refresh(integration_log)
    return integration_log
