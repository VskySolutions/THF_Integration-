import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.sap_concur_invoice_integration_v2.constants import InvoiceActionStatus
from app.features.sap_concur_invoice_integration_v2.models import (
    SAPConcurInvoiceMappingV2,
)


async def create_mapping(
    session: AsyncSession,
    *,
    journalnumber: str,
    sap_concur_invoice_id: str,
    maconomy_invoice_number: int | None,
    allocation_lines_status: dict[str, Any],
    is_submitted: InvoiceActionStatus,
    is_approved: InvoiceActionStatus,
) -> uuid.UUID:
    mapping = SAPConcurInvoiceMappingV2(
        journalnumber=journalnumber,
        sap_concur_invoice_id=sap_concur_invoice_id,
        maconomy_invoice_number=maconomy_invoice_number,
        allocation_lines_status=allocation_lines_status,
        is_submitted=is_submitted,
        is_approved=is_approved,
    )
    session.add(mapping)
    await session.flush()
    mapping_id = mapping.id
    await session.commit()
    return mapping_id
