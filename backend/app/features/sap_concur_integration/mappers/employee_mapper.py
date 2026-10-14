from typing import Any


def map_owner_to_maconomy_employee(
    owner_login_id: str, employees: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Map a SAP Concur OwnerLoginID to a Maconomy employee by matching email.

    Shared by the batch sync router and the retry service — Req[#16] §6
    (relocated from routers/create_maconomy_expense_sheet.py to avoid a
    router↔service circular import).
    """
    if not owner_login_id:
        return None
    owner_login_id_lower = owner_login_id.lower()
    for employee in employees:
        if employee.get("email", "").lower() == owner_login_id_lower:
            return {
                "email": employee["email"],
                "employeenumber": employee["employeenumber"],
                "employeename": employee.get("employeename", ""),
            }
    return None
