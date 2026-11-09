from datetime import date

import pytest

from app.features.paycor_integration.mappers.timesheet_mapper import (
    TimesheetMappingError,
    assign_employee_paygroups,
    assign_pay_periods,
    group_timesheets_by_pay_period,
)


def test_entries_are_grouped_by_pay_group_and_period() -> None:
    entries = assign_employee_paygroups(
        [
            {
                "employeeNumber": "100",
                "dateWorked": date(2026, 10, 31),
            },
            {
                "employeeNumber": "100",
                "dateWorked": date(2026, 11, 1),
            },
        ],
        paygroup_by_employee={
            "100": "weekly-group",
        },
    )

    entries = assign_pay_periods(
        entries,
        pay_schedules_by_group={
            "weekly-group": [
                {
                    "payPeriodStart": date(2026, 10, 25),
                    "payPeriodEnd": date(2026, 10, 31),
                },
                {
                    "payPeriodStart": date(2026, 11, 1),
                    "payPeriodEnd": date(2026, 11, 7),
                },
            ],
        },
    )

    groups = group_timesheets_by_pay_period(
        entries
    )

    assert set(groups) == {
        (
            "weekly-group",
            date(2026, 10, 25),
            date(2026, 10, 31),
        ),
        (
            "weekly-group",
            date(2026, 11, 1),
            date(2026, 11, 7),
        ),
    }


def test_missing_employee_pay_group_is_rejected() -> None:
    with pytest.raises(
        TimesheetMappingError,
        match="Paycor pay group is unavailable",
    ):
        assign_employee_paygroups(
            [
                {
                    "employeeNumber": "100",
                    "dateWorked": date(2026, 10, 26),
                }
            ],
            paygroup_by_employee={},
        )


def test_date_outside_pay_period_is_rejected() -> None:
    with pytest.raises(
        TimesheetMappingError,
        match="No Paycor pay period contains",
    ):
        assign_pay_periods(
            [
                {
                    "employeeNumber": "100",
                    "payGroupId": "weekly-group",
                    "dateWorked": date(2026, 11, 1),
                }
            ],
            pay_schedules_by_group={
                "weekly-group": [
                    {
                        "payPeriodStart": date(2026, 10, 25),
                        "payPeriodEnd": date(2026, 10, 31),
                    }
                ],
            },
        )
