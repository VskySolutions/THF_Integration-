from typing import Any


def map_concur_expense_report_to_maconomy_expensesheet(
    expense_sheet_data: dict[str, Any],
) -> dict[str, Any]:
    report_name = expense_sheet_data.get("reportname")
    report_id = expense_sheet_data.get("reportid")
    business_purpose = expense_sheet_data.get("businesspurpose")
    approval_status = expense_sheet_data.get("approvalStatus")

    if not report_id or not report_name:
        raise ValueError("SAP Concur reportid and reportname are required")

    return {
        "data": {
            "description": str(report_name),
            # "expensesheetnumber": str(report_id),
            "purposedescription": str(business_purpose),
            "approvalstatus": str(approval_status),
        },
        "offset":0,"limit":100,"row":"end"
    }