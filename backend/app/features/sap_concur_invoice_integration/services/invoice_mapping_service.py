import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.sap_concur_invoice_integration.models.invoice_mapping import (
    SAPConcurInvoiceMapping,
)


async def create_mapping(
    session: AsyncSession,
    *,
    journalnumber: str,
    sap_concur_invoice_id: str,
    journallinenumber: int | None = None,
    allocation_lines_status: dict | None = None,
) -> SAPConcurInvoiceMapping:
    mapping = SAPConcurInvoiceMapping(
        journalnumber=journalnumber,
        sap_concur_invoice_id=sap_concur_invoice_id,
        journallinenumber=journallinenumber,
        allocation_lines_status=allocation_lines_status,
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return mapping


async def list_mappings(
    session: AsyncSession, *, offset: int, limit: int
) -> list[SAPConcurInvoiceMapping]:
    statement = (
        select(SAPConcurInvoiceMapping)
        .order_by(SAPConcurInvoiceMapping.created_on_utc.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.scalars(statement)
    return list(result)


async def get_mapping(
    session: AsyncSession, mapping_id: uuid.UUID
) -> SAPConcurInvoiceMapping | None:
    return await session.get(SAPConcurInvoiceMapping, mapping_id)


async def get_mapping_by_invoice_id(
    session: AsyncSession, invoice_id: str
) -> SAPConcurInvoiceMapping | None:
    statement = select(SAPConcurInvoiceMapping).where(
        SAPConcurInvoiceMapping.sap_concur_invoice_id == invoice_id
    )
    return await session.scalar(statement)


async def update_mapping_allocation_lines_status(
    session: AsyncSession,
    mapping_id: uuid.UUID,
    allocation_lines_status: dict,
) -> SAPConcurInvoiceMapping | None:
    mapping = await session.get(SAPConcurInvoiceMapping, mapping_id)
    if mapping is None:
        return None
    mapping.allocation_lines_status = allocation_lines_status
    await session.commit()
    await session.refresh(mapping)
    return mapping
