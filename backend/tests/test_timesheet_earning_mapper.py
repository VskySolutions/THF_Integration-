import pytest

from app.features.paycor_integration.mappers.timesheet_earning_mapper import (
    TimesheetTaskNotMappedError,
    resolve_paycor_earning_code,
)
from app.features.paycor_integration.services.paycor_timesheet_service import (
    PaycorTimesheetService,
)


@pytest.mark.parametrize(
    ("task_name", "earning_code"),
    [
        ("23002", "PTO"),
        ("23003", "LVEXC"),
        ("23004", "LVFML"),
        ("23005", "HOL"),
        ("23006", "LVOOO"),
        ("23007", "LVPL"),
        ("23008", "3ps"),
        ("23009", "BRV"),
        ("23010", "Jury"),
        ("24508", "OC"),
    ],
)
def test_known_tasks_map_to_paycor_earnings(
    task_name: str,
    earning_code: str,
) -> None:
    assert (
        resolve_paycor_earning_code(task_name)
        == earning_code
    )


def test_other_valid_tasks_map_to_regular() -> None:
    assert resolve_paycor_earning_code("22004") == "REG"


def test_missing_task_is_rejected() -> None:
    with pytest.raises(TimesheetTaskNotMappedError):
        resolve_paycor_earning_code(None)


def test_paycor_earning_lookup_preserves_exact_code_casing() -> None:
    lookup = PaycorTimesheetService._build_earning_code_lookup(
        [
            {"code": "ST-Time"},
            {"code": "3ps"},
            {"code": "Jury"},
        ]
    )

    assert lookup == {
        "ST-TIME": "ST-Time",
        "3PS": "3ps",
        "JURY": "Jury",
    }
