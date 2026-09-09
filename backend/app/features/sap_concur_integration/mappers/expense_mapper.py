from typing import Any


def map_concur_expense_to_maconomy_expense(
    expense_data: dict[str, Any],
) -> dict[str, Any]:
    expense_id = expense_data.get("expenseid")
    expense_type = expense_data.get("expenseType", {}).get("name")
    transaction_date = expense_data.get("transactionDate")
    business_purpose = expense_data.get("businessPurpose")
    amount = expense_data.get("transactionAmount")
    currency = expense_data.get("currency")
    location = expense_data.get("location", {}).get("name")
    department = expense_data.get("location") # Form Field
    
    payment_type = expense_data.get("paymentType").get("name")
    vendor_description = expense_data.get("vendor")
    # client_engagement = expense_data.get("jobnumber")
    travel_reason = expense_data.get("travelreason")

    if not expense_id:
        raise ValueError("SAP Concur expense_id are required")

    return {
        "data":{
            "purposename": str(business_purpose),
            "text": str(expense_type), #taskname = Number of the expense type
            "specification4name": str(location),
            "entrydate": str(transaction_date),
            "locationname": str(department),
            "currency": str(currency),
            "amountbase": str(amount),
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
        "vendor": str(expense.get("vendor", {}).get("name", "")),
        "location": str(expense.get("location", {}).get("name", "")),
        "department": str(expense.get("department", "")),
    }

