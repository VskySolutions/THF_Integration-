"""Apply THF weekly time-calculation rules."""

from decimal import Decimal, InvalidOperation
from typing import Any


WEEKLY_REGULAR_THRESHOLD = Decimal("40")

PAID_LEAVE_EARNING_CODES = {
    "PTO",
    "HOL",
    "LVEXC",
    "LVFML",
    "LVPL",
    "3PS",
    "OC",
}


class TimesheetCalculationError(ValueError):
    """Raised when weekly hours cannot be calculated."""


def calculate_weekly_earnings(
    daily_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Apply THF REG, ST, and OT rules.

    The input must already contain normalized daily records
    with employeeNumber, dateWorked, earningCode,
    earningHours and departmentCode.
    """

    if not daily_entries:
        return []

    entries = [
        _normalize_entry(entry)
        for entry in daily_entries
    ]

    _validate_single_employee_week(entries)

    entries.sort(
        key=lambda entry: (
            str(entry.get("dateWorked", "")),
            str(entry.get("sourceLineNumber", "")),
            str(entry.get("sourceInstanceKey", "")),
        )
    )

    worked_hours = sum(
        (
            entry["earningHours"]
            for entry in entries
            if entry["earningCode"] == "REG"
        ),
        Decimal("0"),
    )

    paid_leave_hours = sum(
        (
            entry["earningHours"]
            for entry in entries
            if entry["earningCode"]
            in PAID_LEAVE_EARNING_CODES
        ),
        Decimal("0"),
    )

    excess_worked_hours = max(
        worked_hours
        - WEEKLY_REGULAR_THRESHOLD,
        Decimal("0"),
    )

    straight_time_hours = min(
        excess_worked_hours,
        paid_leave_hours,
    )

    overtime_hours = max(
        excess_worked_hours
        - straight_time_hours,
        Decimal("0"),
    )

    remaining_reg = min(
        worked_hours,
        WEEKLY_REGULAR_THRESHOLD,
    )

    remaining_st = straight_time_hours
    remaining_ot = overtime_hours

    calculated_entries: list[
        dict[str, Any]
    ] = []

    for entry in entries:
        if entry["earningCode"] != "REG":
            calculated_entries.append(entry)
            continue

        entry_hours = entry["earningHours"]

        for earning_code in (
            "REG",
            "ST",
            "OT",
        ):
            if entry_hours <= 0:
                break

            if earning_code == "REG":
                available_hours = remaining_reg

            elif earning_code == "ST":
                available_hours = remaining_st

            else:
                available_hours = remaining_ot

            allocated_hours = min(
                entry_hours,
                available_hours,
            )

            if allocated_hours <= 0:
                continue

            calculated_entry = dict(entry)

            calculated_entry["earningCode"] = (
                earning_code
            )

            calculated_entry["earningHours"] = (
                allocated_hours
            )

            calculated_entries.append(
                calculated_entry
            )

            entry_hours -= allocated_hours

            if earning_code == "REG":
                remaining_reg -= allocated_hours

            elif earning_code == "ST":
                remaining_st -= allocated_hours

            else:
                remaining_ot -= allocated_hours

        if entry_hours > 0:
            raise TimesheetCalculationError(
                "Unable to allocate all worked hours"
            )

    return calculated_entries


def _normalize_entry(
    entry: dict[str, Any],
) -> dict[str, Any]:
    normalized_entry = dict(entry)

    earning_code = str(
        entry.get("earningCode") or ""
    ).strip().upper()

    if not earning_code:
        raise TimesheetCalculationError(
            "Earning code is required"
        )

    normalized_entry["earningCode"] = (
        earning_code
    )

    normalized_entry["earningHours"] = (
        _parse_hours(
            entry.get("earningHours")
        )
    )

    return normalized_entry


def _validate_single_employee_week(
    entries: list[dict[str, Any]],
) -> None:
    employee_weeks = {
        (
            str(
                entry.get("employeeNumber")
                or ""
            ).strip(),
            str(
                entry.get("periodStart")
                or ""
            ).strip(),
        )
        for entry in entries
    }

    if len(employee_weeks) != 1:
        raise TimesheetCalculationError(
            "Calculation must contain exactly "
            "one employee and one week"
        )

    employee_number, period_start = next(
        iter(employee_weeks)
    )

    if not employee_number:
        raise TimesheetCalculationError(
            "Employee number is required"
        )

    if not period_start:
        raise TimesheetCalculationError(
            "Period start is required"
        )


def _parse_hours(
    value: Any,
) -> Decimal:
    if isinstance(value, bool):
        raise TimesheetCalculationError(
            "Invalid earning hours"
        )

    try:
        hours = Decimal(str(value))

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as exc:
        raise TimesheetCalculationError(
            "Invalid earning hours"
        ) from exc

    if hours < 0:
        raise TimesheetCalculationError(
            "Earning hours cannot be negative"
        )

    return hours