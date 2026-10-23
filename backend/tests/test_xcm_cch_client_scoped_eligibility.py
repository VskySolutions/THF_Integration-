from app.features.xcm_cch_client_scoped_integration.services.maconomy_service import (
    MaconomyService,
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
