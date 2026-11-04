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

# Temporary until Pay Group is mapped from Maconomy.
TEMPORARY_PAYCOR_PAY_GROUP_ID = (
    "71c9338a-4c28-0000-0000-0000712f0300"
)

DEFAULT_PAYCOR_PAY_NUMBER = 0


class TimesheetMappingError(ValueError):
    """Raised when a timesheet cannot be mapped."""


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
        ],
        Decimal,
    ] = defaultdict(
        lambda: Decimal("0")
    )

    for entry in calculated_entries:
        employee_number = str(
            entry["employeeNumber"]
        ).strip()

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
                    TEMPORARY_PAYCOR_PAY_GROUP_ID
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
