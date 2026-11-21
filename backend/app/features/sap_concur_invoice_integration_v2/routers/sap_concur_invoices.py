"""Manual SAP Concur vendor invoice sync using the v2 Maconomy flow."""

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
from app.features.sap_concur_invoice_integration_v2.constants import (
    IntegrationAction,
    IntegrationStatus,
    ProcessingStage,
)
from app.features.sap_concur_invoice_integration_v2.schemas.sap_concur_invoices import (
    RetryInvoiceSyncRequest,
)
from app.features.sap_concur_invoice_integration_v2.services import (
    integration_log_service,
    invoice_mapping_service,
)
from app.features.sap_concur_invoice_integration_v2.services.maconomy_invoice_service import (
    MaconomyInvoiceService,
    MaconomyInvoiceServiceError,
)
from app.features.sap_concur_invoice_integration_v2.services.sap_concur_invoice_service import (
    SAPConcurInvoiceNotFoundError,
    SAPConcurInvoiceService,
    SAPConcurInvoiceServiceError,
)

router = APIRouter(
    prefix="/sap-concur-invoices-v2",
    tags=["sap-concur-invoice-integration-v2"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
require_active_invoice_sync = Depends(
    require_active_integration_service(
        IntegrationServiceIdentifier.MACONOMY_SAP_CONCUR_INVOICE_V2_SYNC
    )
)


def _invoice_id(entry: dict[str, Any]) -> str:
    invoice = entry["invoice"]
    return str(invoice.get("PaymentRequestId") or invoice.get("ID") or "").strip()


def _sap_line_id(line: Any, index: int) -> str:
    if isinstance(line, dict):
        for key in ("LineItemId", "ID", "LineNumber"):
            value = line.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return str(index)


async def _save_log(
    session: AsyncSession,
    *,
    invoice_id: str = "N/A",
    mapping_id: uuid.UUID | None = None,
    status: IntegrationStatus,
    stage: ProcessingStage,
    message: str,
    details: dict[str, Any],
    action: IntegrationAction = IntegrationAction.CREATE,
) -> None:
    try:
        await integration_log_service.create_log(
            session,
            mapping_id=mapping_id,
            invoice_id=invoice_id,
            status=status,
            message=message[:1000],
            processing_stage=stage,
            details=details,
            action=action,
        )
    except Exception:
        await session.rollback()


async def _log_invoice(
    session: AsyncSession,
    entry: dict[str, Any],
    invoice: dict[str, Any],
    lines: list[dict[str, Any]],
    *,
    action: IntegrationAction = IntegrationAction.CREATE,
) -> tuple[IntegrationStatus, str]:
    invoice_id = invoice["invoice_id"]
    mapping_id = None
    failed_lines = [line for line in lines if line["status"] == "FAILED"]

    if invoice["status"] == "FAILED":
        invoice_status = IntegrationStatus.FAILED
        stage = ProcessingStage.INVOICE_CREATION
        message = f"Invoice creation failed: {invoice['message']}"
    else:
        allocation_status = {}
        for line in lines:
            index = line["line_index"]
            line_id = _sap_line_id(entry["lineItems"][index], index)
            allocation_status[line_id] = (
                line["maconomy_line_number"]
                if line["status"] == "SUCCESS"
                else line["message"]
            )
        try:
            mapping_id = await invoice_mapping_service.create_mapping(
                session,
                journalnumber=invoice["journalnumber"],
                sap_concur_invoice_id=invoice_id,
                maconomy_invoice_number=invoice["maconomy_invoice_number"],
                allocation_lines_status=allocation_status,
            )
        except Exception:
            await session.rollback()

        created_lines = len(lines) - len(failed_lines)
        message = f"Invoice created with {created_lines}/{len(lines)} allocation rows"
        if warning := invoice.get("warning"):
            message = f"{message}. {warning}"
        if failed_lines:
            invoice_status = IntegrationStatus.PARTIALLY_SUCCESS
            stage = ProcessingStage.LINE_CREATION
        else:
            invoice_status = IntegrationStatus.SUCCESS
            stage = ProcessingStage.COMPLETED

    await _save_log(
        session,
        mapping_id=mapping_id,
        invoice_id=invoice_id or "N/A",
        status=invoice_status,
        stage=stage,
        message=message,
        details={
            "invoice": invoice,
            "lines": lines,
            "validation_failures": [
                {
                    "line_index": line["line_index"],
                    "reason": line["reason"],
                    "message": line["message"],
                }
                for line in failed_lines
                if "reason" in line
            ],
        },
        action=action,
    )
    return invoice_status, message


async def _fetch_entries() -> list[dict[str, Any]]:
    concur_service = SAPConcurInvoiceService()
    digests = await concur_service.get_all_invoice_digests()
    entries = []
    seen_ids: set[str] = set()
    for digest in digests:
        invoice_id = str(digest.get("PaymentRequestId") or digest.get("Id") or "").strip()
        if not invoice_id or invoice_id in seen_ids:
            continue
        seen_ids.add(invoice_id)
        entry = await concur_service.get_invoice_details(invoice_id=invoice_id)
        entries.append({
            "invoice": entry.get("invoice") or {},
            "lineItems": entry.get("lineItems") or [],
        })
    return entries


async def _filter_synced(
    session: AsyncSession,
    maconomy_service: MaconomyInvoiceService,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    invoice_ids = [_invoice_id(entry) for entry in entries]
    lookup_ids = [invoice_id for invoice_id in invoice_ids if invoice_id]
    matches = await maconomy_service.get_existing_invoice_ids(lookup_ids) if lookup_ids else []
    existing_by_id = {
        str(match["sap_invoice_id"]).strip(): match
        for match in matches
        if match.get("sap_invoice_id")
    }
    pending = []
    for invoice_id, entry in zip(invoice_ids, entries, strict=True):
        match = existing_by_id.get(invoice_id) if invoice_id else None
        if match is None:
            pending.append(entry)
            continue
        await _save_log(
            session,
            invoice_id=invoice_id,
            status=IntegrationStatus.SKIPPED,
            stage=ProcessingStage.INVOICE_CREATION,
            message=f"Invoice {invoice_id} already exists in Maconomy (remark5 match)",
            details={"precheck": {"sap_invoice_id": invoice_id, "maconomy": match}},
        )
    return pending


@router.post(
    "/sync-sap-concur-invoices",
    response_model=dict[str, Any],
    dependencies=[require_active_invoice_sync],
)
async def sync_sap_concur_invoices(session: DatabaseSession) -> dict[str, Any]:
    maconomy_service = MaconomyInvoiceService()
    stage = ProcessingStage.INVOICE_FETCH
    operation = "fetch SAP Concur invoices"
    try:
        entries = await _fetch_entries()
        operation = "pre-check existing Maconomy invoices"
        pending = await _filter_synced(session, maconomy_service, entries)
        stage = ProcessingStage.INVOICE_CREATION
        operation = "prepare Maconomy invoice creation"
        results = await maconomy_service.create_invoices(pending) if pending else []
    except (SAPConcurInvoiceServiceError, MaconomyInvoiceServiceError, httpx.HTTPError) as exc:
        await _save_log(
            session,
            status=IntegrationStatus.FAILED,
            stage=stage,
            message=f"Failed to {operation}: {exc}",
            details={"stage": stage.value, "error": str(exc)[:1000]},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    invoices: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for entry, (invoice, invoice_lines) in zip(pending, results, strict=True):
        await _log_invoice(session, entry, invoice, invoice_lines)
        invoices.append(invoice)
        lines.extend(invoice_lines)

    created_invoices = sum(invoice["status"] == "SUCCESS" for invoice in invoices)
    created_lines = sum(line["status"] == "SUCCESS" for line in lines)
    invoice_create = bool(invoices) and created_invoices == len(invoices)
    lines_created = invoice_create and created_lines == len(lines)
    response = {
        "invoice_create": invoice_create,
        "lines_created": lines_created,
        "invoices": invoices,
        "lines": lines,
    }

    if not pending:
        run_status = IntegrationStatus.SKIPPED
        stage = ProcessingStage.INVOICE_FETCH
        message = (
            f"All {len(entries)} retrieved invoices already exist in Maconomy"
            if entries
            else "No SAP Concur invoices found in the current sync window"
        )
    else:
        if lines_created:
            run_status = IntegrationStatus.SUCCESS
            stage = ProcessingStage.COMPLETED
        elif created_invoices:
            run_status = IntegrationStatus.PARTIALLY_SUCCESS
            stage = (
                ProcessingStage.LINE_CREATION if invoice_create else ProcessingStage.INVOICE_CREATION
            )
        else:
            run_status = IntegrationStatus.FAILED
            stage = ProcessingStage.INVOICE_CREATION
        message = (
            f"Created {created_invoices}/{len(invoices)} invoices and "
            f"{created_lines}/{len(lines)} allocation rows"
        )

    await _save_log(session, status=run_status, stage=stage, message=message, details=response)
    return response


@router.post(
    "/retry-invoice-sync",
    response_model=dict[str, Any],
    dependencies=[require_active_invoice_sync],
)
async def retry_invoice_sync(
    session: DatabaseSession,
    request: RetryInvoiceSyncRequest,
) -> dict[str, Any]:
    """Retry creation of one SAP Concur invoice and its lines in Maconomy."""
    invoice_id = request.invoice_id.strip()
    if not invoice_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invoice_id is required")

    action = IntegrationAction.RETRY_CREATE
    stage = ProcessingStage.INVOICE_FETCH
    operation = "fetch the invoice from SAP Concur"
    try:
        entry = await SAPConcurInvoiceService().get_invoice_details(invoice_id=invoice_id)
        invoice_id = _invoice_id(entry) or invoice_id

        stage = ProcessingStage.INVOICE_CREATION
        operation = "check for the invoice in Maconomy"
        maconomy_service = MaconomyInvoiceService()
        matches = await maconomy_service.get_existing_invoice_ids([invoice_id])
        match = next(
            (
                item for item in matches
                if str(item.get("sap_invoice_id") or "").strip() == invoice_id
            ),
            None,
        )
        if match is not None:
            message = "This invoice already exists in Maconomy."
            await _save_log(
                session,
                invoice_id=invoice_id,
                action=action,
                status=IntegrationStatus.SKIPPED,
                stage=stage,
                message=message,
                details={"precheck": {"sap_invoice_id": invoice_id, "maconomy": match}},
            )
            return {
                "invoice_id": invoice_id,
                "status": IntegrationStatus.SKIPPED,
                "message": message,
                "invoice": None,
                "lines": [],
            }

        operation = "prepare invoice creation in Maconomy"
        ((invoice, lines),) = await maconomy_service.create_invoices([entry])
    except (SAPConcurInvoiceServiceError, MaconomyInvoiceServiceError, httpx.HTTPError) as exc:
        if isinstance(exc, SAPConcurInvoiceNotFoundError):
            status_code = status.HTTP_404_NOT_FOUND
            message = "This invoice is not present in SAP Concur."
        else:
            status_code = status.HTTP_502_BAD_GATEWAY
            message = f"Unable to {operation}."
        await _save_log(
            session,
            invoice_id=invoice_id,
            action=action,
            status=IntegrationStatus.FAILED,
            stage=stage,
            message=message,
            details={"stage": stage.value, "error": str(exc)[:1000]},
        )
        raise HTTPException(status_code, message) from exc

    outcome, message = await _log_invoice(session, entry, invoice, lines, action=action)
    return {
        "invoice_id": invoice_id,
        "status": outcome,
        "message": message,
        "invoice": invoice,
        "lines": lines,
    }
