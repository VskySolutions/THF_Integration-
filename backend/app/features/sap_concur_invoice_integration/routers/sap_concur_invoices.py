"""SAP Concur invoice sync endpoint (AP invoices) — 4-phase flow (FR-1).

Phase 1-2: retrieve Concur invoice digests + details.
Phase 3: create ONE static journal (card pane) per run with every
retrieved Concur invoice as a dynamically mapped table row beneath it
(Req[#21] FR-11/FR-12, WO[#21.9]).
Phase 4 (INTERLEAVED, WO[#27.8]): vendorinvoiceallocation lines for an
invoice are created immediately after THAT invoice's row — row 1 ->
invoice 1's lines -> row 2 -> invoice 2's lines -> ... — inside
``create_journal_with_invoices``; the router only builds the entries
(``{"invoice", "lineItems"}``) and returns the structured flags response
{invoice_create, lines_created, journal, invoices, lines, line_error}.
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
    """Full sync: digests -> details -> journal + rows -> lines -> flags."""
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

    # --- Phases 3+4 in ONE pass (WO[#27.8]): entries pair each Concur
    # invoice with its lineItems; the service creates row N and then
    # immediately invoice N's allocation lines before row N+1 (FR-12
    # amended, user 2026-11-10 — supersedes the separate phase-4 batch
    # call). Line batches are NOT built here and no journalnumber
    # short-circuit lives in the router: linkage extraction (primary
    # path panes->card->records->data->journalnumber) and the D-6 skip
    # are both inside the service. ---
    entries: list[dict[str, Any]] = [
        {
            "invoice": entry.get("invoice") or {},
            "lineItems": entry.get("lineItems") or [],
        }
        for entry in results
    ]
    if not entries:
        # No Concur invoices -> no journal is created (unchanged guard).
        return {
            "invoice_create": False,
            "lines_created": False,
            "journal": None,
            "invoices": [],
            "lines": [],
            "line_error": None,
        }

    maconomy_service = MaconomyInvoiceService()
    try:
        journal_result = await maconomy_service.create_journal_with_invoices(
            entries=entries
        )
    except MaconomyInvoiceServiceError as exc:
        # Journal is the batch prerequisite -> 500 (FR-11 amended;
        # mirrors expense-sync prerequisite failures).
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # --- Structured response (FR-9 / A-5): both flags true only on full
    # success; journal/invoices/lines/line_error are additive
    # diagnostics — assembly is byte-identical to the pre-WO[#27.8]
    # contract, values now come from the interleaved run. ---
    created_invoices = journal_result.get("invoices", [])
    lines = journal_result.get("lines", [])
    line_error = journal_result.get("line_error")
    invoice_create = (
        bool(journal_result.get("journal"))
        and bool(created_invoices)
        and all(e.get("status") == "SUCCESS" for e in created_invoices)
    )
    lines_created = (
        invoice_create
        and not line_error
        and all(e.get("status") == "SUCCESS" for e in lines)
    )
    return {
        "invoice_create": invoice_create,
        "lines_created": lines_created,
        "journal": journal_result.get("journal"),
        "invoices": created_invoices,
        "lines": lines,
        "line_error": line_error,
    }
