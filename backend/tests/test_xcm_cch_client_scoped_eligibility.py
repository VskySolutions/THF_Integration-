import asyncio
from unittest.mock import AsyncMock

import pytest

from app.features.xcm_cch_client_scoped_integration.services.maconomy_service import (
    MaconomyService,
    MaconomyServiceError,
)


def _eligible_job(**overrides: object) -> dict[str, object]:
    job: dict[str, object] = {
        "jobnumber": "ENG-1001",
        "employee6_email": "billing.manager@example.com",
        "spec5_email": "cse@example.com",
        "purposename_email": "engagement.partner@example.com",
        "specification2_description": "Tax Return",
    }
    job.update(overrides)
    return job


def test_job_is_eligible_when_all_required_values_are_present() -> None:
    assert MaconomyService.cch_eligibility_failure(_eligible_job()) is None


def test_missing_roles_are_reported_by_business_name() -> None:
    reason = MaconomyService.cch_eligibility_failure(
        _eligible_job(employee6_email="", spec5_email=None)
    )

    assert reason == (
        "Engagement ENG-1001 is not eligible to sync with CCH: "
        "Billing Manager and CSE are not assigned to the engagement."
    )


def test_blank_or_default_return_type_is_ineligible() -> None:
    for return_type in (None, "", "   ", "default", " DEFAULT "):
        reason = MaconomyService.cch_eligibility_failure(
            _eligible_job(specification2_description=return_type)
        )

        assert reason == (
            "Engagement ENG-1001 is not eligible to sync with CCH: "
            "Return Type is not set for the engagement."
        )


def test_role_and_return_type_reasons_are_combined() -> None:
    reason = MaconomyService.cch_eligibility_failure(
        _eligible_job(
            purposename_email=" ",
            specification2_description="default",
        )
    )

    assert reason == (
        "Engagement ENG-1001 is not eligible to sync with CCH: "
        "Engagement Partner is not assigned to the engagement. "
        "Return Type is not set for the engagement."
    )


def test_job_discovery_uses_text18_mapping() -> None:
    assert "text18=''" in MaconomyService._job_restriction(None)
    assert "text18=''" in MaconomyService._job_restriction(["ENG-1001"])
    job = {"template": False, "closed": False, "locationname": "2", "text18": ""}
    assert MaconomyService._is_syncable_tax_job(job)
    assert not MaconomyService._is_syncable_tax_job({**job, "text18": "TASK-1"})


@pytest.mark.parametrize("task_id", [None, "TASK-1"])
def test_maconomy_writeback_uses_date3_and_optional_text18(task_id: str | None) -> None:
    service = MaconomyService.__new__(MaconomyService)
    saved_job = {"versionnumber": 8, "date3": "2026-12-31"}
    if task_id is not None:
        saved_job["text18"] = task_id
    service._bind_job = AsyncMock(
        side_effect=[
            ({"versionnumber": 7, "text18": ""}, "instance", "token"),
            (saved_job, "instance", "token"),
        ]
    )
    service._post_job_request = AsyncMock()

    version = asyncio.run(
        service._attempt_job_cch_log(
            job_number="ENG-1001",
            expected_version=7,
            period_end_date="12/31/2026",
            task_id=task_id,
        )
    )

    expected_data = {"date3": "2026-12-31"}
    if task_id is not None:
        expected_data["text18"] = task_id
    assert version == 8
    service._post_job_request.assert_awaited_once_with(
        "/instances/instance/data/panes/card/0",
        {"data": expected_data},
        concurrency_token="token",
    )


def test_maconomy_writeback_rejects_existing_text18_mapping() -> None:
    service = MaconomyService.__new__(MaconomyService)
    service._bind_job = AsyncMock(
        return_value=({"versionnumber": 7, "text18": "TASK-OLD"}, "instance", "token")
    )
    service._post_job_request = AsyncMock()

    with pytest.raises(MaconomyServiceError, match="already has a text18 mapping"):
        asyncio.run(
            service._attempt_job_cch_log(
                job_number="ENG-1001",
                expected_version=7,
                period_end_date="12/31/2026",
                task_id="TASK-NEW",
            )
        )
    service._post_job_request.assert_not_awaited()
