from typing import Any
from decimal import Decimal

def map_concur_expense_to_maconomy_expense(
    expense_data: dict[str, Any],
    expense_sheet_number: str | None = None,
    employee_number: str | None = None,
) -> dict[str, Any]:
    expense_id = expense_data.get("expenseId")
    # expense_type = expense_data.get("expenseType", {}).get("name")
    transaction_date = expense_data.get("transactionDate")
    amount = expense_data.get("transactionAmount", {}).get("value")
    currency = expense_data.get("transactionAmount", {}).get("currencyCode")
    
    # exchangerate = expense_data.get("exchangerate", {}).get("value")
    # location = expense_data.get("location", {}).get("city") if expense_data.get("location", {}).get("city") else ""
    # business_purpose = expense_data.get("businessPurpose")
    # payment_type = expense_data.get("paymentType", {}).get("name")
    # vendor_description = expense_data.get("vendor", {}).get("description")

    # department =
    # client_engagement = expense_data.get("jobnumber")
    # travel_reason = expense_data.get("travelreason")
    

    if not expense_id:
        raise ValueError("SAP Concur expense_id are required")
    print("Done")
    return {
        "data":{     
            "specification4name": "10",
            "entrydate": str(transaction_date),
            "entityname": "ADM",
            "currency": str(currency),
            "unitpricecurrency": float(amount) if amount is not None else 0.0,
            "numberof": 1 ,#float(exchangerate), # Exchange rate
            "expensesheetlinetext10": str(expense_id) if expense_id else "",
            # "taskname": "400",
            # "description": str(vendor_description) if vendor_description else ""
        },
        "offset":0,"limit":100,"row":"end"    
    }


def map_expense_to_summary(
    expense: dict[str, Any],
) -> dict[str, Any]:
    """
    Map a full SAP Concur expense to a simplified summary with only required fields.
    
    Args:
        expense: Full expense dict from SAP Concur API.
        
    Returns:
        dict with expense_type, transaction_date, payment_type, currency,
        business_purpose, amount, location, and department fields.
    """
    return {
        "expense_type": str(expense.get("expenseType", {}).get("name", "")),
        "transaction_date": str(expense.get("transactionDate", "")),
        "payment_type": str(expense.get("paymentType", {}).get("name", "")),
        "currency": str(expense.get("transactionAmount", {}).get("currencyCode", "")),
        "business_purpose": str(expense.get("businessPurpose", "")),
        "amount": expense.get("transactionAmount", {}).get("value", ""),
        "vendor": str(expense.get("vendor", {})),
        "location": str(expense.get("location", {}).get("name", "")),
        "department": str(expense.get("department", "")),
    }

