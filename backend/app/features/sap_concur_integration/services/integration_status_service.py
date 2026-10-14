"""Pure status-resolution helpers for the SAP Concur -> Maconomy workflow.

No I/O and no service imports -- single source of truth for mapping workflow
stage outcomes to the final IntegrationStatus (Req[#15] FR-2 / FR-3 / NFR-4).
Also hosts the pure details/stage template builders shared by the batch sync
router and the retry service (Req[#16] §6).
"""

from typing import Any

from app.features.sap_concur_integration.constants import (
    IntegrationStatus,
    ProcessingStage,
)

# Idempotent Maconomy outcomes count as success for their stage (FR-2.6).
_SUBMITTED_STATUSES = {"SUBMITTED", "ALREADY_SUBMITTED"}
_APPROVED_STATUSES = {"APPROVED", "ALREADY_APPROVED"}


def determine_final_workflow_status(
    *,
    sheet_created: bool,
    total_lines: int,
    failure_count: int,
    submission_status: str,
    approval_status: str,
) -> tuple[IntegrationStatus, str]:
    """Map the outcome of the complete workflow to a final status + reason.

    Stage rules (Req[#15] FR-2):
    - Sheet not created                  -> FAILED
    - Any line failure (partial OR all)  -> PARTIALLY_SUCCESS
    - Submission not completed           -> PARTIALLY_SUCCESS
    - Approval not completed             -> PARTIALLY_SUCCESS
    - All four stages completed OK       -> SUCCESS

    ``total_lines == 0`` counts as a successful line stage (existing
    behavior preserved). ``ALREADY_SUBMITTED`` / ``ALREADY_APPROVED``
    count as success for their stage.
    """
    if not sheet_created:
        return (
            IntegrationStatus.FAILED,
            "Expense sheet was not created in Maconomy",
        )
    if failure_count > 0:
        return (
            IntegrationStatus.PARTIALLY_SUCCESS,
            f"Expense lines incomplete: "
            f"{total_lines - failure_count}/{total_lines} lines succeeded, "
            f"{failure_count} failed",
        )
    if submission_status not in _SUBMITTED_STATUSES:
        return (
            IntegrationStatus.PARTIALLY_SUCCESS,
            f"Submission did not complete "
            f"(status: {submission_status or 'SKIPPED'})",
        )
    if approval_status not in _APPROVED_STATUSES:
        return (
            IntegrationStatus.PARTIALLY_SUCCESS,
            f"Approval did not complete "
            f"(status: {approval_status or 'SKIPPED'})",
        )
    return (
        IntegrationStatus.SUCCESS,
        "Expense sheet, expense lines, submission, and approval "
        "completed successfully",
    )


def determine_final_stage(
    *,
    failure_count: int,
    submission_status: str,
    approval_status: str,
) -> ProcessingStage:
    """Map the failed/non-completed stage to its ProcessingStage label (FR-6).

    Shared by batch sync and retry — Req[#16] §6.
    """
    if failure_count > 0:
        return ProcessingStage.EXPENSE_LINE_CREATION
    if submission_status not in {"SUBMITTED", "ALREADY_SUBMITTED"}:
        return ProcessingStage.SUBMISSION
    if approval_status not in {"APPROVED", "ALREADY_APPROVED"}:
        return ProcessingStage.APPROVAL
    return ProcessingStage.COMPLETED


def truncate_error(value: Any) -> str | None:
    """Truncate error strings to 1000 chars (CCH details convention).

    Shared by batch sync and retry — Req[#16] §6.
    """
    if value is None:
        return None
    text = str(value)
    return text[:1000]


def build_line_stage_details(
    line_results: dict[str, Any], *, aborted_reason: str | None
) -> dict[str, Any]:
    """Build the structured `expense_lines` node for the details JSON (WO#15.3).

    Shared by batch sync and retry — Req[#16] §6.

    Stable shape: status/total/succeeded_count/failed_count/succeeded/failed/
    error. `total == 0` (no Concur expenses) counts as SUCCESS (existing
    behavior preserved). An aborted workflow records SKIPPED + the abort
    reason since lines were never processed.
    """
    total = int(line_results.get("total", 0))
    success_count = int(line_results.get("success_count", 0))
    failure_count = int(line_results.get("failure_count", 0))

    if aborted_reason is not None:
        line_status = "SKIPPED"
    elif failure_count > 0:
        line_status = "PARTIAL" if success_count > 0 else "FAILED"
    else:
        line_status = "SUCCESS"

    return {
        "status": line_status,
        "total": total,
        "succeeded_count": success_count,
        "failed_count": failure_count,
        "succeeded": [
            {
                "expense_id": entry.get("expense_id"),
                "line_number": entry.get("line_number"),
            }
            for entry in line_results.get("succeeded", [])
        ],
        "failed": [
            {
                "expense_id": entry.get("expense_id"),
                "message": truncate_error(entry.get("message")),
                "error_type": entry.get("error_type"),
            }
            for entry in line_results.get("failed", [])
        ],
        "error": truncate_error(aborted_reason),
    }


def build_sheet_not_created_details(
    error_reason: str, *, downstream_error: str = "Expense sheet creation failed"
) -> dict[str, Any]:
    """Compact details payload for logs written BEFORE/THEREFORE without a
    created sheet (WO#15.3): sheet FAILED + downstream stages SKIPPED.

    Shared by batch sync and retry — Req[#16] §6.
    """
    truncated = truncate_error(error_reason)
    return {
        "expense_sheet": {
            "status": "FAILED",
            "expensesheetnumber": None,
            "error": truncated,
        },
        "expense_lines": {"status": "SKIPPED", "error": downstream_error},
        "submission": {"status": "SKIPPED", "error": downstream_error},
        "approval": {"status": "SKIPPED", "error": downstream_error},
    }
