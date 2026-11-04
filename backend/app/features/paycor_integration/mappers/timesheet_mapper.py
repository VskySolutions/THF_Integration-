"""Map Maconomy timesheets to Paycor payroll-hours payloads."""

from collections import defaultdict
from datetime import (
    date,
    datetime,
    time,
    timedelta,
    timezone,
)
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.features.paycor_integration.mappers.timesheet_earning_mapper import (
    resolve_paycor_earning_code,
    TimesheetTaskNotMappedError,
)


DAY_FIELDS = tuple(
    f"numberday{day_number}"
    for day_number in range(1, 8)
)

# Temporary sandbox mappings.
# Remove these when Maconomy entities and Paycor
# departments are aligned.
TEMPORARY_ENTITY_DEPARTMENT_CODES = {
    "3": "4050",  # Human Resources
}

PAYCOR_PAYROLL_INTEGRATION_VENDOR = (
    "THF Maconomy"
)

DEFAULT_PAYCOR_PAY_NUMBER = 0


class TimesheetMappingError(ValueError):
    """Raised when a timesheet cannot be mapped."""


PayPeriodGroupKey = tuple[
    str,
    date,
    date,
]


def map_maconomy_timesheets(
    records: list[dict[str, Any]],
    *,
    department_codes_by_name: dict[
        str,
        str,
    ],
) -> tuple[
    list[dict[str, Any]],
    list[str],
]:
    """Map Maconomy weekly lines into daily entries."""

    daily_entries: list[dict[str, Any]] = []
    skipped_tasks: set[str] = set()
     

    for record in records:
        employee_number = str(
            record.get("employeenumber")
            or ""
        ).strip()

        period_start = date.fromisoformat(
            str(record.get("periodstart"))
        )

        task_name = str(
            record.get("taskname") or ""
        ).strip()

        try:
            earning_code = (
                resolve_paycor_earning_code(
                    task_name
                )
            )

        except TimesheetTaskNotMappedError:
            skipped_tasks.add(
                task_name or "<missing>"
            )

            # Skip the complete Maconomy timesheet line.
            continue

        entity_name = str(
            record.get("entityname")
            or ""
        ).strip()

        # department_code = (
        #     department_codes_by_name.get(
        #         entity_name.casefold()
        #     )
        # )

        # if not employee_number:
        #     raise TimesheetMappingError(
        #         "Maconomy employee number is required"
        #     )

        # if department_code is None:
        #     raise TimesheetMappingError(
        #         "No Paycor department matches "
        #         f"Maconomy entity {entity_name}"
        #     )
        
        normalized_entity_name = (
            entity_name.casefold()
        )

        department_code = (
            TEMPORARY_ENTITY_DEPARTMENT_CODES.get(
                normalized_entity_name
            )
        )

        # When no temporary sandbox mapping exists,
        # use the normal dynamic Paycor lookup.
        if department_code is None:
            department_code = (
                department_codes_by_name.get(
                    normalized_entity_name
                )
            )

        if department_code is None:
            raise ValueError(
                "No Paycor department matches "
                f"Maconomy entity {entity_name}"
    )

        for day_index, field_name in enumerate(
            DAY_FIELDS
        ):
            earning_hours = Decimal(
                str(
                    record.get(field_name)
                    or 0
                )
            )

            if earning_hours <= 0:
                continue

            daily_entries.append(
                {
                    "employeeNumber": (
                        employee_number
                    ),
                    "periodStart": (
                        period_start
                    ),
                    "dateWorked": (
                        period_start
                        + timedelta(
                            days=day_index
                        )
                    ),
                    "departmentCode": (
                        department_code
                    ),
                    "earningCode": (
                        earning_code
                    ),
                    "earningHours": (
                        earning_hours
                    ),
                    "sourceInstanceKey": (
                        record.get("instancekey")
                    ),
                    "sourceLineNumber": (
                        record.get("linenumber")
                    ),
                }
            )

    return (
    daily_entries,
    sorted(skipped_tasks),
    )


def map_timesheets_to_paycor(
    calculated_entries: list[
        dict[str, Any]
    ],
    *,
    earning_codes: dict[str, str],
    paygroup_by_employee: dict[str, str],
    process_id: str,
    timezone_name: str = (
        "America/New_York"
    ),
) -> dict[str, Any]:
    """Build the Paycor payrollhours payload."""

    paycor_timezone = ZoneInfo(
        timezone_name
    )

    aggregated_hours: dict[
        tuple[
            str,
            date,
            date,
            int,
            str,
            str,
        ],
        Decimal,
    ] = defaultdict(
        lambda: Decimal("0")
    )

    for entry in calculated_entries:
        employee_number = str(
            entry["employeeNumber"]
        ).strip()

        pay_group_id = (
            paygroup_by_employee.get(
                employee_number
            )
        )

        if pay_group_id is None:
            raise TimesheetMappingError(
                "Paycor pay group is unavailable "
                "for employee number "
                f"{employee_number}"
            )

        period_start = _as_date(
            entry["periodStart"]
        )

        date_worked = _as_date(
            entry["dateWorked"]
        )

        department_code = int(
            entry["departmentCode"]
        )

        normalized_earning_code = str(
            entry["earningCode"]
        ).strip().upper()

        paycor_earning_code = (
            earning_codes.get(
                normalized_earning_code
            )
        )

        if paycor_earning_code is None:
            raise TimesheetMappingError(
                "Paycor earning code is unavailable: "
                f"{normalized_earning_code}"
            )

        key = (
            employee_number,
            period_start,
            date_worked,
            department_code,
            paycor_earning_code,
            pay_group_id,
        )

        aggregated_hours[key] += Decimal(
            str(entry["earningHours"])
        )

    employees: dict[
        str,
        dict[str, Any],
    ] = {}

    for (
        employee_number,
        period_start,
        date_worked,
        department_code,
        earning_code,
        pay_group_id,
    ), earning_hours in aggregated_hours.items():
        employee = employees.setdefault(
            employee_number,
            {
                "employeeNumber": int(
                    employee_number
                ),
                "importEarnings": [],
            },
        )

        employee["importEarnings"].append(
            {
                "departmentCode": (
                    department_code
                ),
                "earningCode": (
                    earning_code
                ),
                "earningHours": float(
                    earning_hours
                ),
                "businessStartDate": (
                    _to_paycor_datetime(
                        period_start,
                        paycor_timezone,
                    )
                ),
                "businessEndDate": (
                    _to_paycor_datetime(
                        period_start
                        + timedelta(days=6),
                        paycor_timezone,
                    )
                ),
                "dateWorked": (
                    _to_paycor_datetime(
                        date_worked,
                        paycor_timezone,
                    )
                ),
                "payGroupId": (
                    pay_group_id
                ),
                "payNumber": (
                    DEFAULT_PAYCOR_PAY_NUMBER
                ),
            }
        )

    return {
        "integrationVendor": (
            PAYCOR_PAYROLL_INTEGRATION_VENDOR
        ),
        "processId": process_id,
        "importEmployees": list(
            employees.values()
        ),
    }


def assign_employee_paygroups(
    calculated_entries: list[
        dict[str, Any]
    ],
    *,
    paygroup_by_employee: dict[str, str],
) -> list[dict[str, Any]]:
    """Add the employee's Paycor pay group to each entry."""

    resolved_entries: list[
        dict[str, Any]
    ] = []

    for entry in calculated_entries:
        employee_number = str(
            entry.get("employeeNumber")
            or ""
        ).strip()

        pay_group_id = (
            paygroup_by_employee.get(
                employee_number
            )
        )

        if not employee_number:
            raise TimesheetMappingError(
                "Maconomy employee number is required"
            )

        if pay_group_id is None:
            raise TimesheetMappingError(
                "Paycor pay group is unavailable "
                "for employee number "
                f"{employee_number}"
            )

        resolved_entries.append(
            {
                **entry,
                "employeeNumber": employee_number,
                "payGroupId": pay_group_id,
            }
        )

    return resolved_entries


def assign_pay_periods(
    calculated_entries: list[
        dict[str, Any]
    ],
    *,
    pay_schedules_by_group: dict[
        str,
        list[dict[str, date]],
    ],
) -> list[dict[str, Any]]:
    """Match every daily earning to one Paycor pay period."""

    assigned_entries: list[
        dict[str, Any]
    ] = []

    for entry in calculated_entries:
        pay_group_id = str(
            entry.get("payGroupId")
            or ""
        ).strip()

        if not pay_group_id:
            raise TimesheetMappingError(
                "Paycor pay group is required"
            )

        date_worked = _as_date(
            entry.get("dateWorked")
        )

        matching_periods = [
            period
            for period in (
                pay_schedules_by_group.get(
                    pay_group_id,
                    [],
                )
            )
            if (
                period["payPeriodStart"]
                <= date_worked
                <= period["payPeriodEnd"]
            )
        ]

        if not matching_periods:
            raise TimesheetMappingError(
                "No Paycor pay period contains "
                f"date worked {date_worked.isoformat()} "
                f"for pay group {pay_group_id}"
            )

        if len(matching_periods) != 1:
            raise TimesheetMappingError(
                "Multiple Paycor pay periods contain "
                f"date worked {date_worked.isoformat()} "
                f"for pay group {pay_group_id}"
            )

        pay_period = matching_periods[0]

        assigned_entries.append(
            {
                **entry,
                "dateWorked": date_worked,
                "payPeriodStart": (
                    pay_period["payPeriodStart"]
                ),
                "payPeriodEnd": (
                    pay_period["payPeriodEnd"]
                ),
            }
        )

    return assigned_entries


def group_timesheets_by_pay_period(
    calculated_entries: list[
        dict[str, Any]
    ],
) -> dict[
    PayPeriodGroupKey,
    list[dict[str, Any]],
]:
    """Group daily earnings by pay group and pay period."""

    grouped_entries: dict[
        PayPeriodGroupKey,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for entry in calculated_entries:
        pay_group_id = str(
            entry.get("payGroupId")
            or ""
        ).strip()

        if not pay_group_id:
            raise TimesheetMappingError(
                "Paycor pay group is required"
            )

        pay_period_start = _as_date(
            entry.get("payPeriodStart")
        )
        pay_period_end = _as_date(
            entry.get("payPeriodEnd")
        )

        if pay_period_end < pay_period_start:
            raise TimesheetMappingError(
                "Paycor pay period end is before "
                "its start"
            )

        group_key = (
            pay_group_id,
            pay_period_start,
            pay_period_end,
        )

        grouped_entries[group_key].append(
            entry
        )

    return dict(grouped_entries)


def _as_date(
    value: Any,
) -> date:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    return date.fromisoformat(
        str(value)
    )


def _to_paycor_datetime(
    value: date,
    paycor_timezone: ZoneInfo,
) -> str:
    local_datetime = datetime.combine(
        value,
        time(hour=8),
        tzinfo=paycor_timezone,
    )

    return (
        local_datetime
        .astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
