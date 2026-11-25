from datetime import date
from decimal import Decimal

from app.features.paycor_integration.services.timesheet_calculation_service import (
    calculate_weekly_earnings,
)


def _entry(
    earning_code: str,
    earning_hours: str,
) -> dict[str, object]:
    return {
        "employeeNumber": "100",
        "periodStart": date(2026, 11, 16),
        "dateWorked": date(2026, 11, 16),
        "earningCode": earning_code,
        "earningHours": Decimal(earning_hours),
    }


def _hours_by_code(
    entries: list[dict[str, object]],
) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}

    for entry in entries:
        earning_code = str(entry["earningCode"])
        totals[earning_code] = (
            totals.get(earning_code, Decimal("0"))
            + Decimal(str(entry["earningHours"]))
        )

    return totals


def test_hourly_non_exempt_keeps_all_earnings() -> None:
    result = calculate_weekly_earnings(
        [
            _entry("REG", "45"),
            _entry("BRV", "2"),
            _entry("Jury", "1"),
            _entry("LVOOO", "8"),
        ],
        employee_classification="Hourly Non-Exempt",
    )

    assert _hours_by_code(result) == {
        "REG": Decimal("40"),
        "ST-TIME": Decimal("3"),
        "OT": Decimal("2"),
        "BRV": Decimal("2"),
        "JURY": Decimal("1"),
        "LVOOO": Decimal("8"),
    }


def test_salary_non_exempt_keeps_reg_st_and_ot_only() -> None:
    result = calculate_weekly_earnings(
        [
            _entry("REG", "45"),
            _entry("PTO", "2"),
            _entry("BRV", "1"),
            _entry("LVOOO", "8"),
        ],
        employee_classification="Salary Non-Exempt",
    )

    assert _hours_by_code(result) == {
        "REG": Decimal("40"),
        "ST-TIME": Decimal("3"),
        "OT": Decimal("2"),
    }


def test_subcontractor_converts_all_hours_to_regular() -> None:
    result = calculate_weekly_earnings(
        [
            _entry("PTO", "8"),
            _entry("BRV", "4"),
        ],
        employee_classification="Subcontractor",
    )

    assert _hours_by_code(result) == {
        "REG": Decimal("12"),
    }


def test_salary_exempt_produces_no_entries() -> None:
    result = calculate_weekly_earnings(
        [_entry("REG", "40")],
        employee_classification="Salary Exempt",
    )

    assert result == []
