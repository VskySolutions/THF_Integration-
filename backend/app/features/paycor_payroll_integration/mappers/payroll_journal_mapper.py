"""Mappers for Paycor Payroll data to Maconomy General Journal format."""

from datetime import datetime, timezone
from typing import Any


def format_iso_datetime(value: str | datetime | None = None) -> str:
    """
    Format a date/datetime into Paycor's required ISO-8601 format:
    YYYY-MM-DDTHH:MM:SS (e.g. 2026-09-13T00:00:00).
    If value is None, defaults to current UTC start-of-day.
    """
    if not value:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT00:00:00")

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")

    # If it's already a string:
    str_val = str(value).strip()
    if "T" in str_val:
        return str_val

    # If format is YYYY-MM-DD, append T00:00:00
    if len(str_val) == 10 and str_val.count("-") == 2:
        return f"{str_val}T00:00:00"

    return str_val


def map_paycor_gl_to_maconomy_card(
    planner_id: str,
    group_id: str | None = None,
    run_type: str | None = None,
    company_number: str = "100",
    transaction_date: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Map Paycor payroll run details to Maconomy General Journal card header."""
    desc = description or f"Payroll GL - {run_type or 'Payrun'} ({group_id or planner_id})"
    date_val = transaction_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return {
        "companynumber": company_number,
        "automaticvouchervar": True,
        "entrytotalcontrol": 0,
        "description": desc[:100],
        "transactiondate": date_val,
    }


def map_paycor_gl_record_to_maconomy_line(
    record: dict[str, Any],
    default_entry_date: str | None = None,
) -> dict[str, Any]:
    """Map a single Paycor General Ledger line item to a Maconomy journal table line."""
    account_number = (
        record.get("accountNumber")
        or record.get("account")
        or record.get("account_number")
        or ""
    )
    raw_amount = record.get("amount", 0)
    entry_type = (record.get("entryType") or record.get("entry_type") or "").upper()

    try:
        amount = float(raw_amount)
    except (ValueError, TypeError):
        amount = 0.0

    # If negative amount or specified as Credit
    if entry_type == "CREDIT" and amount > 0:
        amount = -amount

    entry_date = (
        record.get("checkDate")
        or record.get("entryDate")
        or default_entry_date
        or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    if "T" in str(entry_date):
        entry_date = str(entry_date).split("T")[0]

    description = (
        record.get("description")
        or record.get("memo")
        or record.get("departmentDescription")
        or ""
    )

    department = record.get("department") or record.get("departmentNumber") or ""
    employee_number = record.get("employeeNumber") or ""

    return {
        "accountnumber": str(account_number).strip(),
        "amount": amount,
        "text": f"{description} {employee_number}".strip()[:100],
        "entrydate": entry_date,
        "department": str(department).strip(),
        "specification4": str(employee_number).strip(),
    }
