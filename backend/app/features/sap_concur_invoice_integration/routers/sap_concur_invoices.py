"""SAP Concur invoice sync endpoints (AP invoices).

Retrieves invoice digests + details from SAP Concur, then creates each
invoice (card first, then its lines) in the Maconomy vendorinvoices
container via MaconomyInvoiceService (Phase 2 of Req[#21], FR-11).
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

# TESTING LIMIT (user decision 2026-10-23): create only ONE vendor invoice
# in Maconomy per run instead of one per Concur invoice (6 today) — avoids
# writing 6 identical static test records into UAT while validating the flow.
_MAX_INVOICES_TO_CREATE = 1


@router.post("/sync-sap-concur-invoices", response_model=list[dict[str, Any]])
async def sync_sap_concur_invoices() -> list[dict[str, Any]]:
    """Retrieve all Concur invoices, then create each in Maconomy."""
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

    # --- Creation phase: invoice (card) first, then its lines ---
    # TESTING LIMIT: only the first retrieved invoice is created (see
    # _MAX_INVOICES_TO_CREATE); the remaining Concur invoices are NOT
    # created in Maconomy for now.
    maconomy_service = MaconomyInvoiceService()
    sync_results: list[dict[str, Any]] = []

    for entry in results[:_MAX_INVOICES_TO_CREATE]:
        invoice = entry.get("invoice", {})
        invoice_id = str(
            invoice.get("PaymentRequestId") or invoice.get("ID") or ""
        ).strip()

        try:
            # create_vendor_invoice(): instance -> init card -> create
            # card -> init table -> for-loop line rows (static mappers).
            maconomy_result = await maconomy_service.create_vendor_invoice()
            sync_results.append(
                {
                    "invoice_id": invoice_id,
                    "status": "SUCCESS",
                    "result": maconomy_result,
                }
            )

        except MaconomyInvoiceServiceError as exc:
            # One failed invoice never terminates the batch
            # (same behavior as the expense-reports sync endpoint).
            sync_results.append(
                {
                    "invoice_id": invoice_id,
                    "status": "FAILED",
                    "message": str(exc),
                }
            )
            continue

    return sync_results
