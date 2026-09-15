import asyncio
from datetime import date
from unittest.mock import AsyncMock, Mock

from app.core.config import Settings
from app.features.xcm_cch_axcess_integration.services.maconomy_service import (
    CUSTOMER_FIELDS,
    MaconomyService,
    SYNCABLE_JOB_FIELDS,
)
from app.features.xcm_cch_axcess_integration.routers.pending_cch_task_mapping_router import (
    router,
)


def test_syncable_jobs_are_open_tax_jobs_without_an_xcm_task_id() -> None:
    response = Mock()
    response.json.return_value = {
        "panes": {
            "filter": {
                "meta": {"rowCount": 6},
                "records": [
                    {
                        "data": {
                            "jobnumber": "1",
                            "locationname": "TAX",
                            "closed": False,
                            "text20": None,
                        }
                    },
                    {
                        "data": {
                            "jobnumber": "2",
                            "locationname": "tax",
                            "closed": False,
                            "text20": "",
                        }
                    },
                    {
                        "data": {
                            "jobnumber": "3",
                            "locationname": "TAX",
                            "closed": True,
                            "text20": None,
                        }
                    },
                    {
                        "data": {
                            "jobnumber": "4",
                            "locationname": "AUD",
                            "closed": False,
                            "text20": None,
                        }
                    },
                    {
                        "data": {
                            "jobnumber": "5",
                            "locationname": "TAX",
                            "closed": False,
                            "text20": "existing-xcm-task-id",
                        }
                    },
                    {
                        "data": {
                            "jobnumber": "6",
                            "locationname": "TAX",
                            "closed": False,
                        }
                    },
                ],
            }
        }
    }
    client = Mock()
    client.post = AsyncMock(return_value=response)
    service = MaconomyService(Settings())

    records = asyncio.run(
        service._get_syncable_tax_job_records(
            client,
            "token",
            today=date(2026, 9, 10),
        )
    )

    assert [record["jobnumber"] for record in records] == ["1", "2"]
    response.raise_for_status.assert_called_once_with()
    request = client.post.call_args
    assert request.kwargs["json"] == {
        "restriction": (
            "template=false and closed=false "
            "and createddate>=date(2026,4,9) "
            "and createddate<=date(2026,9,10) "
            "and text20=''"
        ),
        "fields": SYNCABLE_JOB_FIELDS,
        "limit": 2000,
    }


def test_customer_details_are_fetched_once_and_mapped_to_jobs() -> None:
    customer_response = Mock()
    customer_response.json.return_value = {
        "panes": {
            "filter": {
                "meta": {"rowCount": 2},
                "records": [
                    {
                        "data": {
                            "customernumber": "C-100",
                            "fiscalyearendmonth": 6,
                        }
                    },
                    {
                        "data": {
                            "customernumber": "C-200",
                            "fiscalyearendmonth": "december",
                        }
                    },
                ],
            }
        }
    }
    client = Mock()
    client.post = AsyncMock(return_value=customer_response)
    service = MaconomyService(Settings())
    jobs = [
        {"jobnumber": "1", "customernumber": "C-100", "theyear": 2025},
        {"jobnumber": "2", "customernumber": "C-200", "theyear": "2024"},
        {"jobnumber": "3", "customernumber": "C-100", "theyear": 2026},
        {"jobnumber": "4", "customernumber": "C-300", "theyear": 2025},
        {"jobnumber": "5", "customernumber": None, "theyear": 2025},
    ]

    enriched_jobs = asyncio.run(
        service._add_customer_fiscal_year_end_month(client, "token", jobs)
    )

    assert enriched_jobs == [
        {
            "jobnumber": "1",
            "customernumber": "C-100",
            "theyear": 2025,
            "fiscalyearendmonth": 6,
            "periodenddate": "06/30/2025",
        },
        {
            "jobnumber": "2",
            "customernumber": "C-200",
            "theyear": "2024",
            "fiscalyearendmonth": "december",
            "periodenddate": "12/31/2024",
        },
        {
            "jobnumber": "3",
            "customernumber": "C-100",
            "theyear": 2026,
            "fiscalyearendmonth": 6,
            "periodenddate": "06/30/2026",
        },
        {
            "jobnumber": "4",
            "customernumber": "C-300",
            "theyear": 2025,
            "fiscalyearendmonth": None,
            "periodenddate": None,
        },
        {
            "jobnumber": "5",
            "customernumber": None,
            "theyear": 2025,
            "fiscalyearendmonth": None,
            "periodenddate": None,
        },
    ]
    client.post.assert_awaited_once()
    request = client.post.call_args
    assert request.args[0].endswith("/customercard/filter")
    assert request.kwargs["json"] == {
        "restriction": (
            "customernumber='C-100' or customernumber='C-200' or customernumber='C-300'"
        ),
        "fields": CUSTOMER_FIELDS,
        "limit": 3,
    }


def test_job_filter_excludes_project_fields() -> None:
    assert "projectname" not in SYNCABLE_JOB_FIELDS


def test_period_end_date_accepts_maconomy_month_name() -> None:
    assert MaconomyService._calculate_period_end_date(2026, "december") == (
        "12/31/2026"
    )


def test_pending_cch_task_mapping_is_a_post_endpoint() -> None:
    route = next(
        route
        for route in router.routes
        if route.path.endswith("/pending-cch-task-mapping")
    )

    assert route.path == (
        "/xcm-cch-axcess/maconomy-tax-engagements/pending-cch-task-mapping"
    )
    assert route.methods == {"POST"}
