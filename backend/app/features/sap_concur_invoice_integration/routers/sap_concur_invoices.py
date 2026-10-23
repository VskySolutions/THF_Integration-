"""SAP Concur invoice sync endpoint (AP invoices).

Retrieves invoice digests + details from SAP Concur, then syncs them
to Maconomy: ONE static journal (card pane) per run with every
retrieved Concur invoice as a dynamically mapped table row beneath it
(Phase 3 corrected, Req[#21] FR-11/FR-12, WO[#21.9]).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.features.auth.dependencies import require_api_key
from app.features.sap_concur_invoice_integration.services import (
    MaconomyInvoiceService,
    MaconomyInvoiceServiceError,
    SAPConcurInvoiceService,
    SAPConcurInvoiceServiceError,
)


router = APIRouter(
    prefix="/sap-concur-invoices",
    tags=["sap-concur-invoice-integration"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/sync-sap-concur-invoices", response_model=dict[str, Any])
async def sync_sap_concur_invoices() -> dict[str, Any]:
    """Retrieve all Concur invoices, then create one journal + rows."""
    try:
        service = SAPConcurInvoiceService()
        digests = await service.get_all_invoice_digests()

        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for digest in digests:
            invoice_id = str(
                digest.get("PaymentRequestId") or digest.get("Id") or ""
            ).strip()

            if not invoice_id or invoice_id in seen_ids:
                continue
            seen_ids.add(invoice_id)

            results.append(
                await service.get_invoice_details(invoice_id=invoice_id)
            )

    except SAPConcurInvoiceServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # --- Creation phase: ONE static journal, then all Concur
    # invoices as table rows (FR-12 corrected) ---
    invoices = [entry.get("invoice") or {} for entry in results]
    if not invoices:
        return {"journal": None, "invoices": []}

    maconomy_service = MaconomyInvoiceService()
    try:
        return await maconomy_service.create_journal_with_invoices(
            invoices=invoices
        )
    except MaconomyInvoiceServiceError as exc:
        # Journal is the batch prerequisite -> 500 (FR-11 amended;
        # mirrors expense-sync prerequisite failures).
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
