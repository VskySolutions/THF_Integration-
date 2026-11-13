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

DB logging (WO[#27.9]): mapping + integration-log rows written at the
stage boundaries (reference: sap_concur_integration router pattern) —
logging never masks or changes the sync outcome.

Pre-check (WO[#27.11]): once all Concur invoices are retrieved, one
filtered Maconomy call (``remark5`` = Concur invoice id) finds invoices
already synced — only the non-matching ones proceed to creation;
matched invoices get a SKIPPED integration-log row.
"""

import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.integration_services import (
    IntegrationServiceIdentifier,
    require_active_integration_service,
)
from app.features.sap_concur_invoice_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
    ProcessingStage,
)
from app.features.sap_concur_invoice_integration.services import (
    MaconomyInvoiceService,
    MaconomyInvoiceServiceError,
    SAPConcurInvoiceService,
    SAPConcurInvoiceServiceError,
    integration_log_service,
    invoice_mapping_service,
)


router = APIRouter(
    prefix="/sap-concur-invoices",
    tags=["sap-concur-invoice-integration"],
    dependencies=[Depends(require_api_key)],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


def _sap_line_id(line_item: dict[str, Any] | None, line_index: int) -> str:
    """SAP Concur line id for the allocation-map key (WO[#27.9], WO[#27.12]).

    ``LineItemId`` -> ``ID`` -> ``LineNumber`` -> ``str(line_index)``
    fallback. ``LineItemId`` is the live-confirmed per-line id (2026-11-11
    probe, e.g. ``D5FC26E64574214DB85F31860CC12CBB``); the index fallback
    is last resort only, so the map stays complete if a line has no id.
    """
    if isinstance(line_item, dict):
        for key in ("LineItemId", "ID", "LineNumber"):
            value = line_item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return str(line_index)


def _extract_allocation_line_number(result: Any) -> str | None:
    """Maconomy allocation line number from a line-POST response
    (WO[#27.9], WO[#27.12]).

    Guarded paths mirroring ``_extract_row_line_number`` (service,
    read-only): ``panes -> table -> records -> data -> linenumber``
    (list scanned in REVERSE — the just-created line is the last
    record, expense ``records[-1]`` convention; present only because
    ``linenumber`` is in the instance table slice, WO[#27.12] Step 1)
    -> ``data.linenumber`` -> root ``linenumber`` -> ``None``.
    """
    if not isinstance(result, dict):
        return None

    candidates: list[Any] = []
    panes = result.get("panes")
    table = panes.get("table") if isinstance(panes, dict) else None
    records = table.get("records") if isinstance(table, dict) else None
    if isinstance(records, list):
        for record in reversed(records):
            data = record.get("data") if isinstance(record, dict) else None
            if isinstance(data, dict):
                candidates.append(data.get("linenumber"))
    elif isinstance(records, dict):
        data = records.get("data")
        if isinstance(data, dict):
            candidates.append(data.get("linenumber"))

    top_data = result.get("data")
    if isinstance(top_data, dict):
        candidates.append(top_data.get("linenumber"))
    candidates.append(result.get("linenumber"))

    for candidate in candidates:
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    return None


async def _save_integration_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    invoice_id: str,
    status: IntegrationStatus,
    stage: ProcessingStage,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist one integration log; a logging failure never breaks the run."""
    try:
        await integration_log_service.create_log(
            session,
            mapping_id=mapping_id,
            invoice_id=invoice_id,
            status=status,
            action=IntegrationAction.CREATE,
            message=message,
            processing_stage=stage,
            details=details,
        )
    except Exception as exc:
        # Safe logging (reference: expense router L865-874/L907-927):
        # never mask or change the processing outcome.
        print(f"[invoice-log] failed to persist integration log: {exc}")


@router.post(
    "/sync-sap-concur-invoices",
    response_model=dict[str, Any],
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_SAP_CONCUR_INVOICE_SYNC
            )
        )
    ],
)
async def sync_sap_concur_invoices(
    session: DatabaseSession,
) -> dict[str, Any]:
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
        # --- Log point 2 (WO[#27.9]): log BEFORE the raise so the
        # abort is persisted (reference: expense pattern). ---
        await _save_integration_log(
            session,
            mapping_id=None,
            invoice_id="N/A",
            status=IntegrationStatus.FAILED,
            stage=ProcessingStage.INVOICE_FETCH,
            message=f"Failed to fetch SAP Concur invoices: {str(exc)[:1000]}",
            details={"stage": "INVOICE_FETCH", "error": str(exc)[:1000]},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # --- Pre-check (WO[#27.11], user 2026-11-11): collect the Concur
    # invoice ids of this window (step 1), ask Maconomy which of them
    # already exist via remark5 (step 2), compare both ends (step 3)
    # and let only the non-matching proceed (step 4). Mirrors the
    # expense report pre-check (sap_concur_integration). ---
    concur_invoice_ids: list[str] = []
    for entry in results:
        invoice = entry.get("invoice") or {}
        lookup_id = str(
            invoice.get("PaymentRequestId") or invoice.get("ID") or ""
        ).strip()
        if lookup_id:
            concur_invoice_ids.append(lookup_id)

    if concur_invoice_ids:
        try:
            existing_invoices = (
                await MaconomyInvoiceService().get_existing_invoice_ids(
                    concur_invoice_ids
                )
            )
        except (MaconomyInvoiceServiceError, httpx.HTTPError) as exc:
            # Fail-closed: without the pre-check a re-run could create
            # duplicate rows -> log BEFORE the 500 (WO[#27.9] pattern;
            # mirrors expense REPORT_FETCH handling).
            await _save_integration_log(
                session,
                mapping_id=None,
                invoice_id="N/A",
                status=IntegrationStatus.FAILED,
                stage=ProcessingStage.INVOICE_FETCH,
                message=(
                    "Failed to pre-check existing Maconomy invoices: "
                    f"{str(exc)[:1000]}"
                ),
                details={"stage": "INVOICE_FETCH", "error": str(exc)[:1000]},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
    else:
        existing_invoices = []

    synced_invoice_ids: set[str] = {
        str(item.get("sap_invoice_id") or "").strip()
        for item in existing_invoices
        if item.get("sap_invoice_id")
    }
    existing_by_id: dict[str, dict[str, Any]] = {
        str(item.get("sap_invoice_id") or "").strip(): item
        for item in existing_invoices
        if item.get("sap_invoice_id")
    }
    unexpected_synced_ids = sorted(
        synced_invoice_ids - set(concur_invoice_ids)
    )
    if unexpected_synced_ids:
        # Tripwire (expense pattern): the restriction should only
        # return requested ids.
        print(
            "WARNING: Maconomy returned invoice ids that were NOT "
            "requested - restriction may not be filtering:",
            unexpected_synced_ids,
        )

    # Step 4: only invoices WITHOUT a Maconomy match proceed; matched
    # ones are recorded as SKIPPED in the integration log (D-4) and
    # never enter the journal phase.
    new_results: list[dict[str, Any]] = []
    for result_entry in results:
        result_invoice = result_entry.get("invoice") or {}
        result_invoice_id = str(
            result_invoice.get("PaymentRequestId")
            or result_invoice.get("ID")
            or ""
        ).strip()
        if result_invoice_id and result_invoice_id in synced_invoice_ids:
            # Blank-id invoices are not pre-checkable and proceed
            # (D-5; the row mapper enforces remark5 at write time).
            await _save_integration_log(
                session,
                mapping_id=None,
                invoice_id=result_invoice_id,
                status=IntegrationStatus.SKIPPED,
                stage=ProcessingStage.JOURNAL_CREATION,
                message=(
                    f"Invoice {result_invoice_id} already exists in "
                    "Maconomy (remark5 match) - creation skipped"
                ),
                details={
                    "precheck": {
                        "sap_invoice_id": result_invoice_id,
                        "maconomy": existing_by_id.get(result_invoice_id),
                    }
                },
            )
            continue
        new_results.append(result_entry)

    # --- Phases 3+4 in ONE pass (WO[#27.8]): entries pair each Concur
    # invoice with its lineItems; the service creates row N and then
    # immediately invoice N's allocation lines before row N+1 (FR-12
    # amended, user 2026-11-10 — supersedes the separate phase-4 batch
    # call). Line batches are NOT built here and no journalnumber
    # short-circuit lives in the router: linkage extraction (primary
    # path panes->card->records->data->journalnumber) and the D-6 skip
    # are both inside the service. Built from ``new_results`` (the
    # pre-check already removed already-synced invoices). ---
    entries: list[dict[str, Any]] = [
        {
            "invoice": entry.get("invoice") or {},
            "lineItems": entry.get("lineItems") or [],
        }
        for entry in new_results
    ]
    if not entries:
        # No NEW invoices -> no journal is created (unchanged guard).
        response = {
            "invoice_create": False,
            "lines_created": False,
            "journal": None,
            "invoices": [],
            "lines": [],
            "line_error": None,
        }
        # --- Log point 1 (WO[#27.9]): empty run -> SKIPPED; distinguish
        # "nothing retrieved" from "all skipped by the pre-check". ---
        if results:
            empty_message = (
                f"All {len(results)} retrieved invoice(s) already synced "
                "in Maconomy; nothing to create"
            )
        else:
            empty_message = (
                "No SAP Concur invoices found in the current sync window"
            )
        await _save_integration_log(
            session,
            mapping_id=None,
            invoice_id="N/A",
            status=IntegrationStatus.SKIPPED,
            stage=ProcessingStage.INVOICE_FETCH,
            message=empty_message,
            details=response,
        )
        return response

    maconomy_service = MaconomyInvoiceService()
    try:
        journal_result = await maconomy_service.create_journal_with_invoices(
            entries=entries
        )
    except MaconomyInvoiceServiceError as exc:
        # Journal is the batch prerequisite -> 500 (FR-11 amended;
        # mirrors expense-sync prerequisite failures).
        # --- Log point 3 (WO[#27.9]): log BEFORE the raise. ---
        await _save_integration_log(
            session,
            mapping_id=None,
            invoice_id="N/A",
            status=IntegrationStatus.FAILED,
            stage=ProcessingStage.JOURNAL_CREATION,
            message=(
                f"Maconomy journal/invoice creation failed: {str(exc)[:1000]}"
            ),
            details={"stage": "JOURNAL_CREATION", "error": str(exc)[:1000]},
        )
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

    # --- Log point 4 (WO[#27.9]): per-invoice mapping (SUCCESS rows
    # only — reference-strict) + one consolidated log per invoice. ---
    journalnumber_value = str(
        journal_result.get("journalnumber") or ""
    ).strip()
    line_items_by_invoice: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        invoice = entry.get("invoice") or {}
        lookup_id = str(
            invoice.get("PaymentRequestId") or invoice.get("ID") or ""
        ).strip()
        if lookup_id:
            line_items_by_invoice[lookup_id] = entry.get("lineItems") or []

    for invoice_entry in created_invoices:
        invoice_id = str(invoice_entry.get("invoice_id") or "").strip()
        invoice_lines = [
            e
            for e in lines
            if str(e.get("invoice_id") or "").strip() == invoice_id
        ]
        line_items = line_items_by_invoice.get(invoice_id, [])
        line_success = sum(
            1 for e in invoice_lines if e.get("status") == "SUCCESS"
        )
        line_total = len(invoice_lines)

        mapping_id: uuid.UUID | None = None
        if invoice_entry.get("status") == "SUCCESS" and invoice_id:
            # Allocation map {<sap line id>: <maconomy line number>}.
            allocation_map: dict[str, Any] = {}
            for line_entry in invoice_lines:
                raw_index = line_entry.get("line_index")
                try:
                    line_index: int | None = int(raw_index)
                except (TypeError, ValueError):
                    line_index = None
                line_item = (
                    line_items[line_index]
                    if line_index is not None
                    and 0 <= line_index < len(line_items)
                    else None
                )
                key = _sap_line_id(
                    line_item,
                    line_index
                    if line_index is not None
                    else len(allocation_map),
                )
                if line_entry.get("status") == "SUCCESS":
                    allocation_map[key] = _extract_allocation_line_number(
                        line_entry.get("result")
                    )
                else:
                    allocation_map[key] = None

            raw_jln = invoice_entry.get("journallinenumber")
            try:
                journallinenumber = (
                    int(raw_jln) if raw_jln is not None else None
                )
            except (TypeError, ValueError):
                journallinenumber = None

            try:
                mapping = await invoice_mapping_service.create_mapping(
                    session,
                    journalnumber=journalnumber_value,
                    journallinenumber=journallinenumber,
                    sap_concur_invoice_id=invoice_id,
                    allocation_lines_status=allocation_map,
                )
                mapping_id = mapping.id
            except Exception as map_exc:
                # Non-fatal (reference metadata-update pattern): the log
                # row is still written with mapping_id=None.
                print(
                    f"[invoice-log] failed to persist invoice mapping for "
                    f"{invoice_id}: {map_exc}"
                )

        # Per-invoice status rules (WO[#27.9]).
        has_line_items = bool(line_items)
        if invoice_entry.get("status") != "SUCCESS":
            inv_status = IntegrationStatus.FAILED
            inv_stage = ProcessingStage.JOURNAL_CREATION
            inv_message = (
                f"Invoice {invoice_id or 'N/A'}: row creation failed: "
                f"{str(invoice_entry.get('message') or '')[:1000]}"
            )
        elif not has_line_items:
            inv_status = IntegrationStatus.SUCCESS
            inv_stage = ProcessingStage.COMPLETED
            inv_message = (
                f"Invoice {invoice_id}: row created; no allocation lines"
            )
        elif line_total == 0:
            # Line items exist but the line phase produced no entries
            # (run-level line_error skip, D-6).
            inv_status = IntegrationStatus.SKIPPED
            inv_stage = ProcessingStage.INVOICE_ALLOCATION_LINE_CREATION
            skip_reason = f": {str(line_error)[:1000]}" if line_error else ""
            inv_message = (
                f"Invoice {invoice_id}: row created; allocation lines "
                f"skipped{skip_reason}"
            )
        elif line_success < line_total:
            inv_status = IntegrationStatus.PARTIALLY_SUCCESS
            inv_stage = ProcessingStage.INVOICE_ALLOCATION_LINE_CREATION
            inv_message = (
                f"Invoice {invoice_id}: row created; allocation lines "
                f"{line_success}/{line_total} created"
            )
        else:
            inv_status = IntegrationStatus.SUCCESS
            inv_stage = ProcessingStage.COMPLETED
            inv_message = (
                f"Invoice {invoice_id}: row created; allocation lines "
                f"{line_success}/{line_total} created"
            )

        await _save_integration_log(
            session,
            mapping_id=mapping_id,
            invoice_id=invoice_id or "N/A",
            status=inv_status,
            stage=inv_stage,
            message=inv_message[:1000],
            details={
                "row": invoice_entry,
                "lines": invoice_lines,
                "line_error": line_error,
            },
        )

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
    response = {
        "invoice_create": invoice_create,
        "lines_created": lines_created,
        "journal": journal_result.get("journal"),
        "invoices": created_invoices,
        "lines": lines,
        "line_error": line_error,
    }

    # --- Log point 5 (WO[#27.9]): run-level summary, details = the
    # exact FR-9 response; status/stage per the run rules. ---
    row_success = sum(
        1 for e in created_invoices if e.get("status") == "SUCCESS"
    )
    line_total_all = len(lines)
    if invoice_create and lines_created:
        run_status = IntegrationStatus.SUCCESS
        run_stage = ProcessingStage.COMPLETED
        run_message = (
            f"Journal {journalnumber_value or 'N/A'}: {row_success}/"
            f"{len(created_invoices)} invoice row(s) and "
            f"{len(lines)}/{line_total_all} allocation line(s) created"
        )
    elif invoice_create:
        run_status = IntegrationStatus.PARTIALLY_SUCCESS
        run_stage = ProcessingStage.INVOICE_ALLOCATION_LINE_CREATION
        run_message = (
            f"Journal {journalnumber_value or 'N/A'}: rows complete; "
            f"allocation lines incomplete "
            f"({sum(1 for e in lines if e.get('status') == 'SUCCESS')}/"
            f"{line_total_all} succeeded)"
        )
    else:
        run_status = IntegrationStatus.FAILED
        run_stage = ProcessingStage.JOURNAL_CREATION
        run_message = (
            f"Journal {journalnumber_value or 'N/A'}: invoice rows "
            f"incomplete ({row_success}/{len(created_invoices)} created)"
        )
    await _save_integration_log(
        session,
        mapping_id=None,
        invoice_id="N/A",
        status=run_status,
        stage=run_stage,
        message=run_message[:1000],
        details=response,
    )
    return response
