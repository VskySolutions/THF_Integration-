from typing import Any


def map_concur_expense_report_to_maconomy_expensesheet(
    expense_sheet_data: dict[str, Any],
) -> dict[str, Any]:
    print("In mapper")
    

    report_name = expense_sheet_data.get("name")
    report_id = expense_sheet_data.get("reportId")
    business_purpose = expense_sheet_data.get("businessPurpose")
    approval_status = expense_sheet_data.get("approvalStatus")
    # print("report_name", report_name, "\n business_purpose:", business_purpose, "\n approval status:", approval_status)

    if not report_id or not report_name:
        raise ValueError("SAP Concur reportId and reportname are required")

    return {
        "data": {
            "description": str(report_name),
            # "expensesheetnumber": str(report_id),
            # "purposedescriptionvar": str(business_purpose),
            # "approvalstatus": str(approval_status),
        },
        "offset":0,"limit":100
    }
