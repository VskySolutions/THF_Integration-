from sqlalchemy.ext.asyncio import AsyncSession

from app.features.sap_concur_vendor_integration.models.vendor_mapping import (
    SAPConcurVendorMapping,
)


async def create_mapping(
    session: AsyncSession,
    *,
    sap_concur_vendor_code: str,
    maconomy_vendor_code: str,
) -> SAPConcurVendorMapping:
    mapping = SAPConcurVendorMapping(
        sap_concur_vendor_code=sap_concur_vendor_code,
        maconomy_vendor_code=maconomy_vendor_code,
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return mapping
