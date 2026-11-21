from typing import Any


def map_concur_expense_report_to_maconomy_expensesheet(
    expense_sheet_data: dict[str, Any],
    employee_number: str | None = None,
    jobnumber: str | None = None,
) -> dict[str, Any]:
    report_name = expense_sheet_data.get("name")
    report_id = expense_sheet_data.get("reportId")
    business_purpose = expense_sheet_data.get("businessPurpose")
    approval_status = expense_sheet_data.get("approvalStatus")

    if not report_id or not report_name:
        raise ValueError("SAP Concur reportId and reportname are required")

    payload_data = {
        "description": str(report_name),
        "expensesheettext1": str(business_purpose),
        "expensesheettext5": str(report_id),
        "employeenumber": str(employee_number) if employee_number else "",
        "currency": "USD"
        # "approvalstatus": str(approval_status),
    }

    # Engagement — only when present in input (Req#26 FR-10/Q-3).
    # taskname is line-only; never written on the expensesheet card
    # (user correction 2026-11-06).
    if jobnumber and str(jobnumber).strip():
        payload_data["jobnumber"] = str(jobnumber).strip()

    return {
        "data": payload_data,
        "offset":0,"limit":100
    }
