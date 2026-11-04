"""Mappers for Paycor Payroll data to Maconomy General Journal format."""

import re
from datetime import datetime, timezone
from typing import Any

from app.features.paycor_payroll_integration.constants import (
    DEFAULT_COMPANY_NUMBER,
    DEFAULT_GL_ACCOUNT_NUMBER,
    DEFAULT_TRANSACTION_TYPE,
    DEFAULT_TYPE_OF_ENTRY,
    DEPARTMENT_ENTITY_CODE_MAP,
)


def resolve_entity_code(department_description: str | None) -> str:
    """Map Paycor departmentDescription to Maconomy Entity Code."""
    if not department_description or not str(department_description).strip():
        return DEPARTMENT_ENTITY_CODE_MAP["DEFAULT"]

    text = str(department_description).strip().upper()

    if re.search(r"\bASSURANCE\b", text):
        return DEPARTMENT_ENTITY_CODE_MAP["ASSURANCE"]
    if re.search(r"\bTAX(ES)?\b", text):
        return DEPARTMENT_ENTITY_CODE_MAP["TAX"]
    if re.search(r"\bADMIN(ISTRATION)?\b", text):
        return DEPARTMENT_ENTITY_CODE_MAP["ADMIN"]
    if re.search(r"\bGCS\b", text):
        return DEPARTMENT_ENTITY_CODE_MAP["GCS"]
    if re.search(r"\bCAS\b", text):
        return DEPARTMENT_ENTITY_CODE_MAP["CAS"]

    return DEPARTMENT_ENTITY_CODE_MAP["DEFAULT"]


def format_iso_datetime(value: str | datetime | None = None) -> str:
    """Format a date/datetime into Paycor's required ISO-8601 format (YYYY-MM-DDTHH:MM:SS)."""
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")

    str_val = str(value).strip()
    if "T" in str_val:
        return str_val

    if len(str_val) == 10 and str_val.count("-") == 2:
        return f"{str_val}T00:00:00"

    return str_val


def group_gl_records_by_department(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group Paycor GL records by departmentDescription."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    unassigned: list[dict[str, Any]] = []

    for record in records:
        dept = (
            record.get("departmentDescription")
            or record.get("department_description")
            or record.get("department")
        )
        if not dept or not str(dept).strip():
            unassigned.append(record)
        else:
            dept_key = str(dept).strip()
            grouped.setdefault(dept_key, []).append(record)

    if unassigned:
        grouped["UNASSIGNED"] = unassigned

    return grouped


def map_paycor_gl_to_maconomy_card(
    planner_id: str,
    group_id: str | None = None,
    run_type: str | None = None,
    company_number: str = DEFAULT_COMPANY_NUMBER,
    transaction_date: str | None = None,
    description: str | None = None,
    department_description: str | None = None,
) -> dict[str, Any]:
    """Map Paycor payroll run details to Maconomy General Journal card header."""
    dept_label = department_description or ""
    desc = (
        description
        or f"Automated SYNC from paycor - {run_type or 'Payrun'} ({group_id or planner_id}) [{dept_label}]"
    )
    date_val = transaction_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return {
        "companynumber": company_number,
        "automaticvouchervar": True,
        "entrytotalcontrol": 0,
        "remark1": desc[:100],
        "postingdate": date_val,
        "defaulttransactiontype": DEFAULT_TRANSACTION_TYPE,
        "entityname": "",
    }


def map_paycor_gl_record_to_maconomy_line(
    record: dict[str, Any],
    default_entry_date: str | None = None,
    employee_id_map: dict[str, str] | None = None,
    department_description: str | None = None,
    work_location_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Map a single Paycor General Ledger line item to a Maconomy journal table line."""
    account_number = DEFAULT_GL_ACCOUNT_NUMBER

    # Extract raw amounts (supports debitAmount/creditAmount or signed amount)
    raw_debit = float(record.get("debitAmount") or 0.0)
    raw_credit = float(record.get("creditAmount") or 0.0)
    raw_amount = record.get("amount")

    # Handle negative amounts: Maconomy rejects negative debitbase or creditbase.
    # In accounting, a negative debit becomes a credit; a negative credit becomes a debit.
    if raw_amount is not None and raw_debit == 0.0 and raw_credit == 0.0:
        val = float(raw_amount)
        if val >= 0:
            debit_val = val
            credit_val = 0.0
        else:
            debit_val = 0.0
            credit_val = abs(val)
    else:
        if raw_debit < 0:
            debit_val = 0.0
            credit_val = abs(raw_debit)
        elif raw_credit < 0:
            debit_val = abs(raw_credit)
            credit_val = 0.0
        else:
            debit_val = raw_debit
            credit_val = raw_credit

    entry_date = (
        record.get("checkDate")
        or record.get("entryDate")
        or default_entry_date
        or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    if "T" in str(entry_date):
        entry_date = str(entry_date).split("T")[0]

    dept_desc = (
        department_description
        or record.get("departmentDescription")
        or record.get("department_description")
        or record.get("department")
        or ""
    )
    entity_code = resolve_entity_code(dept_desc)

    description = (
        record.get("description")
        or record.get("memo")
        or record.get("departmentDescription")
        or ""
    )
    employee_number = record.get("employeeNumber") or ""

    if not employee_number and employee_id_map:
        emp_id = (
            record.get("employeeId")
            or record.get("employeeID")
            or record.get("id")
        )
        if emp_id:
            employee_number = employee_id_map.get(str(emp_id).strip(), "")

    str_emp_number = str(employee_number).strip() if employee_number else ""

    work_location = ""
    if work_location_map:
        dept_id = (
            record.get("departmentId")
            or record.get("departmentID")
            or record.get("department_id")
            or record.get("department")
            or record.get("id")
        )
        if dept_id:
            work_location = work_location_map.get(str(dept_id).strip(), "")

        if not work_location and str_emp_number:
            work_location = work_location_map.get(str_emp_number, "")

    return {
        "accountnumber": account_number,
        "debitbase": debit_val,
        "creditbase": credit_val,
        "entrydate": entry_date,
        "entrytext": f"{description} {str_emp_number}".strip()[:100],
        "entityname": entity_code,
        "employeenumber": str_emp_number,
        "typeofentry": DEFAULT_TYPE_OF_ENTRY,
        "specification4name": work_location,
    }


