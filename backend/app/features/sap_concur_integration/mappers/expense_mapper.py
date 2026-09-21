from typing import Any
from decimal import Decimal

# Department code mapping: SAP Concur department name -> Maconomy code
DEPARTMENT_CODE_MAPPING = {
    "Admin": "ADM",
    "Assurance": "AUD",
    "CAS": "CAS",
    "GCS": "GCS",
    "Tax": "TAX",
}

LOCATION_CODE_MAPPING = {
    "Lakeland": "50",
    "Panama City": "40",
    "Tallahassee": "10",
    "Tampa": "20",
    "Kimley Horne": "19",
    "Bainbridge": "30",
}

EXPENSE_TYPE_CODE_MAPPING = {
    "Airfare": "401",
    "Car Rental": "404",
    "Hotel": "403",
    "Fuel": "",
    "Parking": "406",
    "Personal Car Mileage": "",
    "Runner Mileage": "",
    "Taxi/ Uber": "405",
    "Tolls/Road Charges": "",
    "Entertainment -  Event/Shows": "407",
    "Off Site Meals (Attendees)": "407",
    "On Site Meals (Attendees)": "407",
    "Computer": "",
    "Courier/Shipping/Freight": "",
    "Furniture & Fixtures": "",
    "Leasehold Improvements": "",
    "Office Supplies/Software": "",
    "Internet/Online Fees": "",
    "Phone Expense": "",
    "professional Subscription/Dues": "",
    "Advertising": "",
    "Cable & Internet Expenses": "",
    "Computer Network Services": "",
    "Computer Software & Support": "",
    "Computer Supplies": "",
    "CPE Seminar/Courses": "",
    "CPE Shareholder Courses/Seminars": "",
    "Direct Recruiting - Meals": "",
    "Direct Recruiting Expenses": "",
    "Due from THF D&I": "",
    "Equipment": "",
    "Gifts - Clients": "",
    "Holiday Party": "",
    "Indirect Recruiting Expense": "",
    "Marketing-Contractors": "",
    "Marketing-Practice Development": "",
    "Marketing-Social Media": "",
    "Marketing-Sponsorships": "",
    "Marketing/Promotional Costs": "",
    "Non Reimbursable/Personal Expense": "",
    "Other Administrative": "",
    "Postage & Overnight Expense": "",
    "Prepaid Software": "",
    "Rental Expense": "",
    "Repairs & Maintenance": "",
    "Security": "",
    "Seminar/Course Fees": "",
    "Staff Awards/Incentives": "",
    "Subscriptions/Newspaper/Books": "",
    "Technology Training Expense": "",
    "Tuition/Training Reimbursement": "",
    "Utilities": ""
}

DEFAULT_DEPARTMENT_CODE = "-"
DEFAULT_LOCATION_CODE = "-"
DEFAULT_EXPENSE_TYPE_CODE = ""


def get_location_code(department_name: str) -> str:
    """
    Convert SAP Concur department name to Maconomy department code.
    
    Args:
        department_name: SAP Concur department name (e.g., "Admin", "Assurance")
        
    Returns:
        Maconomy department code (e.g., "ADM", "AUD") or default code "-" if not found
    """
    if not department_name:
        return DEFAULT_DEPARTMENT_CODE
    return DEPARTMENT_CODE_MAPPING.get(department_name, DEFAULT_DEPARTMENT_CODE)


def get_department_code(location_name: str) -> str:
    """
    Convert SAP Concur department name to Maconomy department code.
    
    Args:
        department_name: SAP Concur department name (e.g., "Admin", "Assurance")
        
    Returns:
        Maconomy department code (e.g., "ADM", "AUD") or default code "-" if not found
    """
    if not location_name:
        return DEFAULT_LOCATION_CODE
    return DEPARTMENT_CODE_MAPPING.get(location_name, DEFAULT_LOCATION_CODE)


def get_expense_type_code(expense_type: str) -> str:

    if not expense_type:
        return DEFAULT_EXPENSE_TYPE_CODE
    return DEPARTMENT_CODE_MAPPING.get(expense_type, DEFAULT_EXPENSE_TYPE_CODE)


def map_concur_expense_to_maconomy_expense(
    expense_data: dict[str, Any],
    expense_sheet_number: str | None = None,
    employee_number: str | None = None,
    custom_data_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expense_id = expense_data.get("expenseId")
    expense_type = expense_data.get("expenseType", {}).get("name")
    transaction_date = expense_data.get("transactionDate")
    amount = expense_data.get("approvedAmount", {}).get("value")
    currency = expense_data.get("approvedAmount", {}).get("currencyCode")
    exchangerate = expense_data.get("exchangerate", {}).get("value")
    business_purpose = expense_data.get("businessPurpose")
    # payment_type = expense_data.get("paymentType", {}).get("name")
    # vendor_description = expense_data.get("vendor", {}).get("description"

    # Extract custom data values with fallback to existing logic
    custom_location = custom_data_values.get("location", "") if custom_data_values else ""
    custom_department = custom_data_values.get("department", "") if custom_data_values else ""
    custom_travel_reason = custom_data_values.get("travel_reason", "") if custom_data_values else ""
    custom_job_number = custom_data_values.get("job_number", "") if custom_data_values else ""

    print("custom_location:",custom_location , "custom_department:",custom_department,"custom_travel_reason:",custom_travel_reason,"custom_job_number:",custom_job_number)

    if not expense_id:
        raise ValueError("SAP Concur expense_id are required")

    # Check if job number has a valid value (not None, not empty, not whitespace)
    has_valid_job_number = custom_job_number and custom_job_number.strip()

    # Start with base payload
    payload_data = {
        "text": str(business_purpose),
        "specification4name": get_location_code(custom_location),
        "entrydate": str(transaction_date),
        "entityname": get_department_code(custom_department),
        "currency": str(currency),
        "unitpricecurrency": float(amount)* 100 if amount is not None else 0.0,
        "numberof": float(exchangerate) if exchangerate is not None else 1.0,
        "expensesheetlinetext10": str(expense_id) if expense_id else "",
        "jobnumber": "10102",
        "taskname": "401",

    }

    # Conditionally add jobnumber and taskname only if job number has valid value
    # if has_valid_job_number:
    #     payload_data["jobnumber"] = str(custom_job_number)
    #     payload_data["taskname"] = get_expense_type_code(expense_type)

    return {
        "data": payload_data,
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

