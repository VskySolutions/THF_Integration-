"""Apply THF weekly time-calculation rules."""

from collections import defaultdict
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

    The input must contain normalized daily records
    for exactly one employee and one week.
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
            int(
                entry.get("sourceLineNumber")
                or 0
            ),
            str(
                entry.get(
                    "sourceInstanceKey",
                    "",
                )
            ),
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

    overtime_hours = (
        excess_worked_hours
        - straight_time_hours
    )

    remaining_hours = {
        "REG": min(
            worked_hours,
            WEEKLY_REGULAR_THRESHOLD,
        ),
        "ST": straight_time_hours,
        "OT": overtime_hours,
    }

    calculated_entries: list[
        dict[str, Any]
    ] = []

    for entry in entries:
        if entry["earningCode"] != "REG":
            calculated_entries.append(entry)
            continue

        entry_hours = entry["earningHours"]

        for (
            earning_code,
            available_hours,
        ) in remaining_hours.items():
            if entry_hours <= 0:
                break

            allocated_hours = min(
                entry_hours,
                available_hours,
            )

            if allocated_hours <= 0:
                continue

            calculated_entries.append(
                {
                    **entry,
                    "earningCode": earning_code,
                    "earningHours": (
                        allocated_hours
                    ),
                }
            )

            entry_hours -= allocated_hours

            remaining_hours[
                earning_code
            ] -= allocated_hours

        if entry_hours > 0:
            raise TimesheetCalculationError(
                "Unable to allocate all worked hours"
            )

    return calculated_entries


def calculate_all_weekly_earnings(
    daily_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Calculate earnings for every employee and week."""

    entries_by_employee_week: dict[
        tuple[str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for entry in daily_entries:
        key = (
            str(
                entry.get("employeeNumber")
                or ""
            ).strip(),
            str(
                entry.get("periodStart")
                or ""
            ).strip(),
        )

        entries_by_employee_week[key].append(
            entry
        )

    calculated_entries: list[
        dict[str, Any]
    ] = []

    for key in sorted(entries_by_employee_week):
        calculated_entries.extend(
            calculate_weekly_earnings(
                entries_by_employee_week[key]
            )
        )

    return calculated_entries


def _normalize_entry(
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Normalize one daily earning entry."""

    normalized_entry = dict(entry)

    earning_code = str(
        entry.get("earningCode") or ""
    ).strip().upper()

    if not earning_code:
        raise TimesheetCalculationError(
            "Earning code is required"
        )

    normalized_entry[
        "earningCode"
    ] = earning_code

    normalized_entry[
        "earningHours"
    ] = _parse_hours(
        entry.get("earningHours")
    )

    return normalized_entry


def _validate_single_employee_week(
    entries: list[dict[str, Any]],
) -> None:
    """Validate that entries belong to one employee and week."""

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
    """Convert and validate an earning-hours value."""

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