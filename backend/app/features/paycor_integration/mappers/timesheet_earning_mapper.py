"""Map Maconomy tasks to Paycor earning codes."""

from typing import Any


class TimesheetTaskNotMappedError(ValueError):
    """Raised when a Maconomy task has no Paycor mapping."""


REGULAR_EARNING_TASKS = {
    "1001", "1002", "1003", "1004", "1005",
    "2001", "2002", "2003", "2004", "2005",
    "3001", "3002", "3003", "3004", "3005",
    "4001",
    "5001", "5002", "5003", "5004", "5005",
    "5006", "5007", "5008", "5009", "5010",
    "5011", "5012", "5013", "5014", "5015",
    "5016",
    "6001",
    "7001",
    "8001",
    "9001",
    "9999",
    "10001",
    "11001",
    "12001", "12002", "12003", "12004",
    "12005", "12006", "12007", "12008",
    "12009", "12010", "12011", "12012",
    "12013", "12014", "12015", "12016",
    "12017", "12018",
    "14513", "14514",
    "15001",
    "16001", "16002",
    "17001",
    "18001", "18002", "18003",
    "19001",
    "20001",
    "21001",
    "22001",
    "23001",
    "24001",
    "25001",
    "26001", "26002", "26003", "26004",
    "26005", "26006", "26007", "26008",
    "26009", "26010", "26011", "26012",
    "26013", "26014", "26015",
}


TASK_TO_PAYCOR_EARNING_CODE: dict[str, str] = {
    task_name: "REG"
    for task_name in REGULAR_EARNING_TASKS
}

TASK_TO_PAYCOR_EARNING_CODE.update(
    {
        "13001": "LVEXC",
        "13002": "LVFML",
        "13003": "HOL",
        "13004": "LVOOO",
        "13005": "LVPL",
        "13006": "PTO",
        "13007": "3PS",
        "14508": "OC",
    }
)


def resolve_paycor_earning_code(
    task_name: Any,
) -> str:
    """Resolve a Maconomy task into a Paycor earning code."""

    normalized_task_name = str(
        task_name or ""
    ).strip()

    if not normalized_task_name:
        raise TimesheetTaskNotMappedError(
            "Maconomy task name is missing"
        )

    earning_code = (
        TASK_TO_PAYCOR_EARNING_CODE.get(
            normalized_task_name
        )
    )

    if earning_code is None:
        raise TimesheetTaskNotMappedError(
            "No Paycor earning mapping is configured "
            f"for Maconomy task {normalized_task_name}"
        )

    return earning_code