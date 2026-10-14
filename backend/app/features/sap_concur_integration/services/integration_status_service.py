"""Pure status-resolution helpers for the SAP Concur -> Maconomy workflow.

No I/O and no service imports -- single source of truth for mapping workflow
stage outcomes to the final IntegrationStatus (Req[#15] FR-2 / FR-3 / NFR-4).
"""

from app.features.sap_concur_integration.constants import IntegrationStatus

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
