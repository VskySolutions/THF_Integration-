"""Retry-resume workflow for SAP Concur -> Maconomy expense sync (Req[#16]).

Single-report retry: resolves the report's owner, inspects the live Maconomy
sheet state (submitted/approved), and resumes from the appropriate stage
(sheet creation -> line reconciliation -> submission -> approval) without
repeating completed stages. Duplicate prevention: existence re-check before
sheet creation, `expensesheetlinetext10` line dedupe, idempotent ALREADY_*
submit/approve. Exactly ONE consolidated `action=RETRY_CREATE` integration-log row
is written per attempt (FR-18/FR-19/FR-20).
"""

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.sap_concur_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
    ProcessingStage,
)
from app.features.sap_concur_integration.mappers import (
    map_owner_to_maconomy_employee,
)
from app.features.sap_concur_integration.services import (
    expensesheet_expensereport_mapping_service,
    integration_log_service,
)
from app.features.sap_concur_integration.services.integration_status_service import (
    build_line_stage_details,
    build_sheet_not_created_details,
    determine_final_stage,
    determine_final_workflow_status,
    truncate_error,
)
from app.features.sap_concur_integration.services.maconomy_services import (
    MaconomyService,
    MaconomyServiceError,
)
from app.features.sap_concur_integration.services.sap_concur_service import (
    SAPConcurService,
)


async def _save_retry_log(
    session: AsyncSession,
    report_id: str,
    integration_status: IntegrationStatus,
    message: str,
    processing_stage: ProcessingStage,
    employeeemail: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Write the single consolidated RETRY log row (FR-18/FR-19/FR-20)."""
    mapping = await expensesheet_expensereport_mapping_service.get_mapping_by_report_id(
        session, report_id
    )
    await integration_log_service.create_log(
        session,
        mapping_id=mapping.id if mapping else None,
        report_id=report_id,
        status=integration_status,
        action=IntegrationAction.RETRY_CREATE,
        message=message,
        employeeemail=employeeemail,
        processing_stage=processing_stage,
        details=details,
    )


async def _safe_retry_log(
    session: AsyncSession, **log_kwargs: Any
) -> None:
    """Non-fatal wrapper: a logging failure must never mask the outcome (FR-20)."""
    try:
        await _save_retry_log(session, **log_kwargs)
    except Exception as log_exc:
        print(
            f"Failed to write integration log for report "
            f"{log_kwargs.get('report_id')}: {log_exc}"
        )


def _classify_sheet_state(
    sheet: dict[str, Any] | None,
) -> tuple[ProcessingStage | None, str | None, bool, bool, str | None]:
    """Derive the resume point from the live Maconomy sheet state (FR-7).

    Returns (resume_point, expensesheetnumber, submitted, approved,
    employeenumber). resume_point is None when no sheet exists (full path).
    """
    if not sheet:
        return None, None, False, False, None
    sheet_no = sheet.get("expensesheetnumber")
    submitted = bool(sheet.get("submitted"))
    approved = bool(sheet.get("approved"))
    employee_number = str(sheet.get("employeenumber") or "") or None
    if submitted and approved:
        return ProcessingStage.COMPLETED, sheet_no, submitted, approved, employee_number
    if submitted:
        # FR-7.2: submitted but not approved -> resume at approval only.
        return ProcessingStage.APPROVAL, sheet_no, submitted, approved, employee_number
    # FR-7.3: sheet exists, not submitted -> resume at line reconciliation.
    return ProcessingStage.EXPENSE_LINE_CREATION, sheet_no, submitted, approved, employee_number


async def retry_expense_report_sync(
    session: AsyncSession, *, report_id: str
) -> dict[str, Any]:
    """Retry-resume one SAP Concur report into Maconomy (Req[#16])."""
    try:
        return await _run_retry_expense_report_sync(session, report_id=report_id)
    except HTTPException:
        # Inner paths already wrote their single log row before raising.
        raise
    except Exception as exc:
        # Gap protection: unexpected error that bypassed all inner log paths.
        await _safe_retry_log(
            session,
            report_id=report_id,
            integration_status=IntegrationStatus.FAILED,
            message=f"Retry processing failed: {exc}",
            processing_stage=ProcessingStage.EXPENSE_SHEET_CREATION,
            details=build_sheet_not_created_details(
                f"Retry processing failed: {exc}",
                downstream_error="Unexpected error",
            ),
        )
        raise


async def _run_retry_expense_report_sync(
    session: AsyncSession, *, report_id: str
) -> dict[str, Any]:
    print("======= retry_expense_report_sync ==========")

    # --- Shared workflow locals (WO[#16.2] 4.4) ---
    abort_reason: str | None = None
    user_id: str | None = None
    employee_email: str | None = None
    employee_number: str | None = None
    mapping = None
    existing_lines_count: int | None = None
    missing_lines_created = 0
    total = 0
    failure_count = 0
    line_results: dict[str, Any] = {
        "succeeded": [],
        "failed": [],
        "total": 0,
        "success_count": 0,
        "failure_count": 0,
    }

    # ============ Stage 1 — candidates + report match (FR-2..FR-5) ============
    report_id_norm = str(report_id).strip()
    try:
        candidates = (
            await SAPConcurService().get_retry_candidate_expense_reports_from_sap_concur()
        )
    except Exception as exc:
        message = f"Failed to fetch retry candidate reports from SAP Concur: {exc}"
        await _safe_retry_log(
            session,
            report_id=report_id_norm,
            integration_status=IntegrationStatus.FAILED,
            message=message,
            processing_stage=ProcessingStage.REPORT_FETCH,
            details=build_sheet_not_created_details(message),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message
        ) from exc

    match = next(
        (
            c
            for c in candidates
            if str(c.get("ID") or "").strip() == report_id_norm
        ),
        None,
    )
    if match is None:
        # FR-5: not found — log once, return structured FAILED response.
        message = (
            f"No SAP Concur expense report found with report_id: {report_id_norm}"
        )
        await _safe_retry_log(
            session,
            report_id=report_id_norm,
            integration_status=IntegrationStatus.FAILED,
            message=message,
            processing_stage=ProcessingStage.REPORT_FETCH,
            details={
                "expense_sheet": {
                    "status": "SKIPPED",
                    "expensesheetnumber": None,
                    "error": truncate_error(message),
                },
                "expense_lines": {
                    "status": "SKIPPED",
                    "error": "Not processed: report not found",
                },
                "submission": {
                    "status": "SKIPPED",
                    "error": "Not processed: report not found",
                },
                "approval": {
                    "status": "SKIPPED",
                    "error": "Not processed: report not found",
                },
            },
        )
        return {
            "report_id": report_id_norm,
            "status": IntegrationStatus.FAILED.value,
            "resume_stage": ProcessingStage.REPORT_FETCH.value,
            "message": message,
            "result": None,
        }

    owner_login_id = str(match.get("OwnerLoginID") or "").strip()
    employee_email = owner_login_id

    # ============ Stage 2 — Maconomy sheet state (FR-6/FR-7) ============
    try:
        sheets = await MaconomyService().get_expense_sheets_by_report_ids(
            [report_id_norm]
        )
    except Exception as exc:
        message = f"Failed to fetch Maconomy expense sheets: {exc}"
        await _safe_retry_log(
            session,
            report_id=report_id_norm,
            integration_status=IntegrationStatus.FAILED,
            message=message,
            processing_stage=ProcessingStage.REPORT_FETCH,
            employeeemail=owner_login_id,
            details=build_sheet_not_created_details(message),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message
        ) from exc

    sheet = next(
        (
            s
            for s in sheets
            if str(s.get("sap_report_id") or "").strip() == report_id_norm
        ),
        None,
    )
    resume_point, sheet_no, sheet_submitted, sheet_approved, employee_number = (
        _classify_sheet_state(sheet)
    )

    if resume_point == ProcessingStage.COMPLETED:
        # FR-7.1: already synchronized — stop; no duplicates created.
        message = (
            f"Expense report {report_id_norm} is already synchronized to "
            f"Maconomy (sheet {sheet_no} submitted and approved)"
        )
        await _safe_retry_log(
            session,
            report_id=report_id_norm,
            integration_status=IntegrationStatus.SKIPPED,
            message=message,
            processing_stage=ProcessingStage.COMPLETED,
            employeeemail=owner_login_id,
            details={
                "expense_sheet": {
                    "status": "CREATED",
                    "expensesheetnumber": sheet_no,
                    "error": None,
                },
                "expense_lines": build_line_stage_details(
                    line_results,
                    aborted_reason="Not evaluated — report already synchronized",
                ),
                "submission": {
                    "status": "ALREADY_SUBMITTED",
                    "submitted": True,
                    "error": None,
                },
                "approval": {
                    "status": "ALREADY_APPROVED",
                    "approved": True,
                    "error": None,
                },
                "retry": {
                    "resume_stage": ProcessingStage.COMPLETED.value,
                    "existing_lines": None,
                    "missing_lines_created": 0,
                },
            },
        )
        return {
            "report_id": report_id_norm,
            "status": IntegrationStatus.SKIPPED.value,
            "resume_stage": ProcessingStage.COMPLETED.value,
            "message": message,
            "result": {
                "expense_sheet_number": sheet_no,
                "submitted": True,
                "approved": True,
                "existing_lines": None,
                "missing_lines_created": 0,
            },
        }

    # ============ Stage 3 — full path only: no sheet exists (FR-8..FR-10) ============
    if resume_point is None:
        try:
            user_id = await SAPConcurService().get_user_id_by_login_id(
                owner_login_id=owner_login_id
            )
            report_detail = await SAPConcurService().get_report_by_id(
                report_id_norm, user_id, context_type="TRAVELER"
            )
        except Exception as exc:
            message = f"Failed to fetch SAP Concur report details: {exc}"
            await _safe_retry_log(
                session,
                report_id=report_id_norm,
                integration_status=IntegrationStatus.FAILED,
                message=message,
                processing_stage=ProcessingStage.EXPENSE_SHEET_CREATION,
                employeeemail=owner_login_id,
                details=build_sheet_not_created_details(message),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message
            ) from exc

        if report_detail is None:
            message = "SAP Concur report not found"
            await _safe_retry_log(
                session,
                report_id=report_id_norm,
                integration_status=IntegrationStatus.FAILED,
                message=message,
                processing_stage=ProcessingStage.EXPENSE_SHEET_CREATION,
                employeeemail=owner_login_id,
                details=build_sheet_not_created_details(message),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=message
            )

        try:
            employees = await MaconomyService().get_employees_by_emails_from_maconomy(
                [owner_login_id]
            )
        except Exception as exc:
            message = f"Failed to fetch Maconomy employees: {exc}"
            await _safe_retry_log(
                session,
                report_id=report_id_norm,
                integration_status=IntegrationStatus.FAILED,
                message=message,
                processing_stage=ProcessingStage.EXPENSE_SHEET_CREATION,
                employeeemail=owner_login_id,
                details=build_sheet_not_created_details(message),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message
            ) from exc

        matched = map_owner_to_maconomy_employee(owner_login_id, employees)
        if matched is None:
            message = (
                f"No matching Maconomy employee found for OwnerLoginID: "
                f"{owner_login_id}"
            )
            await _safe_retry_log(
                session,
                report_id=report_id_norm,
                integration_status=IntegrationStatus.SKIPPED,
                message=message,
                processing_stage=ProcessingStage.EXPENSE_SHEET_CREATION,
                employeeemail=owner_login_id,
                details={
                    "expense_sheet": {
                        "status": "SKIPPED",
                        "expensesheetnumber": None,
                        "error": truncate_error(message),
                    },
                    "expense_lines": {
                        "status": "SKIPPED",
                        "error": "Not processed: no matching employee",
                    },
                    "submission": {
                        "status": "SKIPPED",
                        "error": "Not processed: no matching employee",
                    },
                    "approval": {
                        "status": "SKIPPED",
                        "error": "Not processed: no matching employee",
                    },
                },
            )
            return {
                "report_id": report_id_norm,
                "status": IntegrationStatus.SKIPPED.value,
                "resume_stage": ProcessingStage.EXPENSE_SHEET_CREATION.value,
                "message": message,
                "result": None,
            }
        employee_email = matched["email"]
        employee_number = matched["employeenumber"]

        # NFR-4 pre-create re-check: never race past a concurrently created sheet.
        try:
            recheck_sheets = await MaconomyService().get_expense_sheets_by_report_ids(
                [report_id_norm]
            )
        except Exception as exc:
            message = f"Failed to re-check Maconomy expense sheets before creation: {exc}"
            await _safe_retry_log(
                session,
                report_id=report_id_norm,
                integration_status=IntegrationStatus.FAILED,
                message=message,
                processing_stage=ProcessingStage.EXPENSE_SHEET_CREATION,
                employeeemail=owner_login_id,
                details=build_sheet_not_created_details(message),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message
            ) from exc

        recheck_sheet = next(
            (
                s
                for s in recheck_sheets
                if str(s.get("sap_report_id") or "").strip() == report_id_norm
            ),
            None,
        )
        if recheck_sheet is not None:
            # Adopt the concurrently created sheet; never create a duplicate.
            print(
                f"Pre-create re-check found sheet for report {report_id_norm}; "
                "adopting it instead of creating"
            )
            resume_point, sheet_no, sheet_submitted, sheet_approved, employee_number = (
                _classify_sheet_state(recheck_sheet)
            )
            if resume_point == ProcessingStage.COMPLETED:
                message = (
                    f"Expense report {report_id_norm} is already synchronized "
                    f"to Maconomy (sheet {sheet_no} submitted and approved)"
                )
                await _safe_retry_log(
                    session,
                    report_id=report_id_norm,
                    integration_status=IntegrationStatus.SKIPPED,
                    message=message,
                    processing_stage=ProcessingStage.COMPLETED,
                    employeeemail=owner_login_id,
                    details={
                        "expense_sheet": {
                            "status": "CREATED",
                            "expensesheetnumber": sheet_no,
                            "error": None,
                        },
                        "expense_lines": build_line_stage_details(
                            line_results,
                            aborted_reason="Not evaluated — report already synchronized",
                        ),
                        "submission": {
                            "status": "ALREADY_SUBMITTED",
                            "submitted": True,
                            "error": None,
                        },
                        "approval": {
                            "status": "ALREADY_APPROVED",
                            "approved": True,
                            "error": None,
                        },
                        "retry": {
                            "resume_stage": ProcessingStage.COMPLETED.value,
                            "existing_lines": None,
                            "missing_lines_created": 0,
                        },
                    },
                )
                return {
                    "report_id": report_id_norm,
                    "status": IntegrationStatus.SKIPPED.value,
                    "resume_stage": ProcessingStage.COMPLETED.value,
                    "message": message,
                    "result": {
                        "expense_sheet_number": sheet_no,
                        "submitted": True,
                        "approved": True,
                        "existing_lines": None,
                        "missing_lines_created": 0,
                    },
                }
        else:
            # Create the Maconomy expense sheet (FR-9; single create call — FR-10).
            try:
                maconomy_result = await MaconomyService().create_expense_sheet(
                    report_detail, employee_number=employee_number
                )
            except MaconomyServiceError as exc:
                message = f"Failed to create Maconomy expense sheet: {exc}"
                await _safe_retry_log(
                    session,
                    report_id=report_id_norm,
                    integration_status=IntegrationStatus.FAILED,
                    message=message,
                    processing_stage=ProcessingStage.EXPENSE_SHEET_CREATION,
                    employeeemail=owner_login_id,
                    details=build_sheet_not_created_details(message),
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unable to create or reconcile the expense sheet in Maconomy",
                ) from exc

            try:
                records = maconomy_result["panes"]["card"]["records"]
                sheet_no = records[0]["data"]["expensesheetnumber"]
            except (KeyError, TypeError, IndexError) as exc:
                raise MaconomyServiceError(
                    "Invalid Maconomy expense sheet response"
                ) from exc

            if not isinstance(sheet_no, str) or not sheet_no.strip():
                raise MaconomyServiceError("Invalid Maconomy expense sheet response")

            sheet_submitted = False
            sheet_approved = False
            resume_point = ProcessingStage.EXPENSE_LINE_CREATION

    # --- Ensure mapping row exists (full + resume paths; sheet is known) ---
    mapping = await expensesheet_expensereport_mapping_service.get_mapping_by_report_id(
        session, report_id_norm
    )
    if mapping is None:
        mapping = await expensesheet_expensereport_mapping_service.create_mapping(
            session,
            sap_concur_expensereport_id=report_id_norm,
            maconomy_expensesheet_no=sheet_no,
            maconomy_employee_number=employee_number,
        )

    # ============ Stage 4 — line reconcile (FR-11..FR-15) ============
    # Skipped entirely on the approval-only resume path (FR-7.2).
    if resume_point != ProcessingStage.APPROVAL:
        if user_id is None:
            try:
                user_id = await SAPConcurService().get_user_id_by_login_id(
                    owner_login_id=owner_login_id
                )
            except Exception as exc:
                abort_reason = f"Failed to retrieve SAP Concur user ID: {exc}"

        concur_expenses: list[dict[str, Any]] = []
        if abort_reason is None:
            try:
                concur_expenses = await SAPConcurService().get_expenses_by_report_id(
                    report_id=report_id_norm,
                    user_id=user_id,
                    context_type="TRAVELER",
                )
            except Exception as exc:
                abort_reason = f"Failed to retrieve SAP Concur expenses: {exc}"

        existing_line_rows: list[dict[str, Any]] = []
        if abort_reason is None:
            try:
                existing_line_rows = (
                    await MaconomyService().get_expense_sheet_lines_by_expensesheetnumber(
                        sheet_no
                    )
                )
            except MaconomyServiceError as exc:
                abort_reason = (
                    f"Failed to retrieve Maconomy expense sheet lines: {exc}"
                )

        if abort_reason is None:
            existing_ids = {
                str(r.get("expensesheetlinetext10") or "").strip()
                for r in existing_line_rows
                if str(r.get("expensesheetlinetext10") or "").strip()
            }
            existing_lines_count = len(existing_ids)
            missing_expenses = [
                e
                for e in concur_expenses
                if str(e.get("expenseId") or "").strip() not in existing_ids
            ]

            if not missing_expenses:
                # FR-14: all lines already synchronized — proceed per submission state.
                print(
                    f"Expense lines already synchronized for report "
                    f"{report_id_norm} ({existing_lines_count} existing)"
                )
                line_results = {
                    "succeeded": [
                        {
                            "expense_id": r.get("expensesheetlinetext10"),
                            "line_number": r.get("linenumber"),
                        }
                        for r in existing_line_rows
                        if str(r.get("expensesheetlinetext10") or "").strip()
                        in existing_ids
                    ],
                    "failed": [],
                    "total": len(concur_expenses),
                    "success_count": len(concur_expenses),
                    "failure_count": 0,
                }
                missing_lines_created = 0
            else:
                # FR-15: create ONLY the missing lines (duplicate prevention).
                try:
                    line_results = await MaconomyService().create_expense_line_items(
                        expense_sheet_number=sheet_no,
                        expense_data=missing_expenses,
                        employee_number=employee_number,
                        report_id=report_id_norm,
                        user_id=user_id,
                        context_type="TRAVELER",
                    )
                except MaconomyServiceError as exc:
                    abort_reason = (
                        f"Failed to create Maconomy expense line items: {exc}"
                    )
                else:
                    missing_lines_created = int(line_results.get("success_count", 0))

            # Metadata merge (never clobber lines recorded by earlier attempts).
            if abort_reason is None and mapping is not None:
                new_meta = {
                    str(entry.get("expense_id")): str(entry.get("line_number"))
                    for entry in line_results.get("succeeded", [])
                    if entry.get("expense_id") and entry.get("line_number")
                }
                if new_meta:
                    try:
                        merged_meta = {
                            **(mapping.expense_line_metadata or {}),
                            **new_meta,
                        }
                        await expensesheet_expensereport_mapping_service.update_mapping_metadata(
                            session,
                            mapping_id=mapping.id,
                            expense_line_metadata=merged_meta,
                        )
                    except Exception as meta_exc:
                        print(
                            f"Failed to update expense line metadata for report "
                            f"{report_id_norm} (non-fatal): {meta_exc}"
                        )

        total = int(line_results.get("total", 0))
        failure_count = int(line_results.get("failure_count", 0))

    # ============ Stage 5 — submit (FR-16/FR-17; idempotent) ============
    submission: dict[str, Any] = {
        "expense_sheet_number": sheet_no,
        "submitted": False,
        "status": "SKIPPED",
        "message": "",
    }

    if sheet_submitted:
        # FR-7.2 state-based skip — no submit call.
        submission = {
            "expense_sheet_number": sheet_no,
            "submitted": True,
            "status": "ALREADY_SUBMITTED",
            "message": "Expense sheet already submitted",
        }
    elif abort_reason is not None:
        submission["message"] = f"Submission skipped: {abort_reason}"
    elif not sheet_no:
        submission["message"] = "Submission skipped: no expense sheet number"
    elif failure_count > 0:
        submission["message"] = (
            f"Submission skipped: {failure_count}/{total} expense line(s) failed"
        )
    else:
        try:
            submission = await MaconomyService().submit_expense_sheet(sheet_no)
        except MaconomyServiceError as exc:
            submission.update(
                {"submitted": False, "status": "FAILED", "message": str(exc)}
            )
        except Exception as exc:  # never reach the outer catch-all
            submission.update(
                {"submitted": False, "status": "FAILED", "message": str(exc)}
            )

    submit_log_status = {
        "SUBMITTED": IntegrationStatus.SUCCESS,
        "ALREADY_SUBMITTED": IntegrationStatus.SKIPPED,
        "FAILED": IntegrationStatus.FAILED,
        "SKIPPED": IntegrationStatus.SKIPPED,
    }.get(str(submission.get("status", "")), IntegrationStatus.FAILED)

    # ============ Stage 6 — approve (FR-16/FR-17; idempotent) ============
    approval: dict[str, Any] = {
        "expense_sheet_number": sheet_no,
        "approved": False,
        "status": "SKIPPED",
        "message": "",
    }

    if sheet_approved:
        approval = {
            "expense_sheet_number": sheet_no,
            "approved": True,
            "status": "ALREADY_APPROVED",
            "message": "Expense sheet already approved",
        }
    elif abort_reason is not None:
        approval["message"] = f"Approval skipped: {abort_reason}"
    elif not sheet_no:
        approval["message"] = "Approval skipped: no expense sheet number"
    elif failure_count > 0:
        approval["message"] = (
            f"Approval skipped: {failure_count}/{total} expense line(s) failed"
        )
    elif str(submission.get("status", "")) not in {"SUBMITTED", "ALREADY_SUBMITTED"}:
        approval["message"] = (
            "Approval skipped: submission status "
            f"{submission.get('status', '')}"
        )
    else:
        try:
            approval = await MaconomyService().approve_expense_sheet(sheet_no)
        except MaconomyServiceError as exc:
            approval.update(
                {"approved": False, "status": "FAILED", "message": str(exc)}
            )
        except Exception as exc:  # never reach the outer catch-all
            approval.update(
                {"approved": False, "status": "FAILED", "message": str(exc)}
            )

    approve_log_status = {
        "APPROVED": IntegrationStatus.SUCCESS,
        "ALREADY_APPROVED": IntegrationStatus.SKIPPED,
        "FAILED": IntegrationStatus.FAILED,
        "SKIPPED": IntegrationStatus.SKIPPED,
    }.get(str(approval.get("status", "")), IntegrationStatus.FAILED)

    # ============ Stage 7 — persist mapping stage columns (FR-18) ============
    if mapping is not None:
        try:
            await expensesheet_expensereport_mapping_service.update_mapping_submission_status(
                session,
                mapping_id=mapping.id,
                status=submit_log_status,
            )
        except Exception as status_exc:
            print(
                f"Failed to update mapping submission status for report "
                f"{report_id_norm} (non-fatal): {status_exc}"
            )
        try:
            await expensesheet_expensereport_mapping_service.update_mapping_approval_status(
                session,
                mapping_id=mapping.id,
                status=approve_log_status,
            )
        except Exception as status_exc:
            print(
                f"Failed to update mapping approval status for report "
                f"{report_id_norm} (non-fatal): {status_exc}"
            )

    # ============ Stage 8 — final status + ONE consolidated log (FR-19/FR-27) ============
    submission_status = str(submission.get("status", ""))
    approval_status = str(approval.get("status", ""))

    if abort_reason is not None:
        final_status = IntegrationStatus.PARTIALLY_SUCCESS
        final_stage = ProcessingStage.EXPENSE_LINE_CREATION
        final_message = (
            f"Expense sheet {sheet_no} exists but the retry workflow aborted "
            f"before completion.\n{abort_reason}"
        )
    else:
        final_status, final_reason = determine_final_workflow_status(
            sheet_created=True,
            total_lines=total,
            failure_count=failure_count,
            submission_status=submission_status,
            approval_status=approval_status,
        )
        final_stage = determine_final_stage(
            failure_count=failure_count,
            submission_status=submission_status,
            approval_status=approval_status,
        )
        base_message = (
            f"Retry resumed report {report_id_norm} successfully "
            f"(sheet {sheet_no}: {existing_lines_count} existing line(s), "
            f"{missing_lines_created} created"
        )
        stage_parts: list[str] = []
        if str(submission.get("status", "")) in {"SUBMITTED", "ALREADY_SUBMITTED"}:
            stage_parts.append("submitted")
        if str(approval.get("status", "")) in {"APPROVED", "ALREADY_APPROVED"}:
            stage_parts.append("approved")
        if final_status is IntegrationStatus.SUCCESS:
            final_message = f"{base_message}, {', '.join(stage_parts)})"
        else:
            final_message = f"{base_message})\n{final_reason}"

    log_details: dict[str, Any] = {
        "expense_sheet": {
            "status": "CREATED",
            "expensesheetnumber": sheet_no,
            "error": None,
        },
        "expense_lines": build_line_stage_details(
            line_results,
            aborted_reason=abort_reason
            if abort_reason is not None
            else (
                "Line stage skipped: resume path is approval-only"
                if resume_point == ProcessingStage.APPROVAL
                else None
            ),
        ),
        "submission": {
            "status": submission_status or "SKIPPED",
            "submitted": bool(submission.get("submitted")),
            "error": truncate_error(submission.get("message"))
            if (submission_status or "SKIPPED") == "FAILED"
            else None,
        },
        "approval": {
            "status": approval_status or "SKIPPED",
            "approved": bool(approval.get("approved")),
            "error": truncate_error(approval.get("message"))
            if (approval_status or "SKIPPED") == "FAILED"
            else None,
        },
        "retry": {
            "resume_stage": final_stage.value,
            "existing_lines": existing_lines_count,
            "missing_lines_created": missing_lines_created,
        },
    }

    await _safe_retry_log(
        session,
        report_id=report_id_norm,
        integration_status=final_status,
        message=final_message,
        processing_stage=final_stage,
        employeeemail=employee_email,
        details=log_details,
    )

    return {
        "report_id": report_id_norm,
        "status": final_status.value,
        "resume_stage": final_stage.value,
        "message": final_message,
        "result": {
            "expense_sheet_number": sheet_no,
            "submitted": bool(submission.get("submitted")),
            "approved": bool(approval.get("approved")),
            "existing_lines": existing_lines_count,
            "missing_lines_created": missing_lines_created,
        },
    }
