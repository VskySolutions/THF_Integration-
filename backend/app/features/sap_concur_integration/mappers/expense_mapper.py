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


{"data":{
    "entrydate":"2026-08-26",
    "jobnumber":"10100",
    "text":"",
    "currency":"usd",
    "financevatcode":"",
    "taskname":"400",
    "locationname":"AUD",
    "purposename":"-",
    "unitpricecurrency":0,
    "numberof":1,
    "documentname":"",
    "favorite":"",
    "financevatcode2":""
    ,"financevatcode3":"",
    "vat1currency":0,
    "vat2currency":0,
    "vat3currency":0,
    "specification4name":"19"
    },"offset":0,"limit":100,"row":"end"}
