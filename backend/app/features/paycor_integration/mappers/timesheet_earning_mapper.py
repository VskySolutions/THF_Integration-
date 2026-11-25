"""Map Maconomy tasks to Paycor earning codes."""

from typing import Any


class TimesheetTaskNotMappedError(ValueError):
    """Raised when a Maconomy task is missing."""


TASK_TO_PAYCOR_EARNING_CODE = {
    "23002": "PTO",
    "23003": "LVEXC",
    "23004": "LVFML",
    "23005": "HOL",
    "23006": "LVOOO",
    "23007": "LVPL",
    "23008": "3ps",
    "23009": "BRV",
    "23010": "Jury",
    "24508": "OC",
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

    Known tasks use their respective Paycor earning
    codes. All other valid tasks temporarily use REG.
    """

    normalized_task_name = (
        _normalize_task_name(task_name)
    )

    if normalized_task_name is None:
        raise TimesheetTaskNotMappedError(
            "Maconomy task name is missing"
        )

    mapped_earning_code = (
        TASK_TO_PAYCOR_EARNING_CODE.get(
            normalized_task_name
        )
    )

    if mapped_earning_code is not None:
        return mapped_earning_code

    # Temporary fallback until the client provides an
    # accurate task-to-earning mapping.
    return "REG"
