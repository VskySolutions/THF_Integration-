"""Map Maconomy tasks to Paycor earning codes."""

from typing import Any


class TimesheetTaskNotMappedError(ValueError):
    """Raised when a Maconomy task is missing."""


LEAVE_TASK_TO_PAYCOR_EARNING_CODE = {
    "3200": "LVEXC",
    "3201": "LVFML",
    "3202": "HOL",
    "3203": "LVOOO",
    "3204": "LVPL",
    "3205": "PTO",
    "3206": "3PS",
}


def _normalize_task_name(
    value: Any,
) -> str | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (str, int)):
        normalized_value = str(value).strip()

        return normalized_value or None

    return None


def resolve_paycor_earning_code(
    task_name: Any,
) -> str:
    """
    Resolve a Maconomy task to a Paycor earning code.

    Known leave tasks use their respective leave earning
    codes. All other valid tasks temporarily use REG.
    """

    normalized_task_name = (
        _normalize_task_name(task_name)
    )

    if normalized_task_name is None:
        raise TimesheetTaskNotMappedError(
            "Maconomy task name is missing"
        )

    leave_earning_code = (
        LEAVE_TASK_TO_PAYCOR_EARNING_CODE.get(
            normalized_task_name
        )
    )

    if leave_earning_code is not None:
        return leave_earning_code

    # Temporary fallback until the client provides an
    # accurate task-to-earning mapping.
    return "REG"