"""Verify v2 console progress alongside the sync results and database writes."""

import asyncio
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from app.features.sap_concur_invoice_integration_v2.routers import sap_concur_invoices


@pytest.fixture
def run_sync(monkeypatch, capsys):
    route = sap_concur_invoices
    create_log = AsyncMock()
    create_mapping = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr(route.integration_log_service, "create_log", create_log)
    monkeypatch.setattr(route.invoice_mapping_service, "create_mapping", create_mapping)
    monkeypatch.setattr(
        route.SAPConcurInvoiceService,
        "get_all_invoice_digests",
        AsyncMock(return_value=[{"PaymentRequestId": "PR-1"}]),
    )
    monkeypatch.setattr(
        route.SAPConcurInvoiceService,
        "get_invoice_details",
        AsyncMock(
            return_value={
                "invoice": {
                    "Name": "Test invoice",
                    "InvoiceNumber": "INV-1",
                    "InvoiceDate": "2026-11-01",
                    "PaymentRequestId": "PR-1",
                    "VendorCode": "V-1",
                },
                "lineItems": [
                    {
                        "LineItemId": "L-1",
                        "Engagement": "ENG-1",
                        "Task": "TASK-1",
                        "Department": "Assurance",
                        "UnitPrice": "2",
                    }
                ],
            }
        ),
    )

    real_client = httpx.AsyncClient

    def run(failure=None, existing=False):
        service = route.MaconomyInvoiceService
        monkeypatch.setattr(
            service, "_get_reconnect_token", AsyncMock(return_value="test")
        )
        monkeypatch.setattr(
            service,
            "get_all_vendor_numbers",
            AsyncMock(return_value=set() if failure == "vendor" else {"v-1"}),
        )
        monkeypatch.setattr(
            service, "get_all_entity_names", AsyncMock(return_value={"assurance"})
        )
        monkeypatch.setattr(
            service,
            "get_engagement_tasks",
            AsyncMock(return_value=set() if failure == "task" else {"task-1"}),
        )
        monkeypatch.setattr(
            service,
            "get_existing_invoice_ids",
            AsyncMock(return_value=[{"sap_invoice_id": "PR-1"}] if existing else []),
        )

        def maconomy_response(request):
            suffix = request.url.path.split("/instances", 1)[1]
            if failure and suffix.endswith(failure):
                return httpx.Response(503, text="fixture-only response content")
            headers = {"Maconomy-Concurrency-Control": str(uuid.uuid4())}
            if not suffix:
                payload = {"meta": {"containerInstanceId": str(uuid.uuid4())}}
            elif suffix.endswith("/card"):
                payload = {"journalnumber": "J-1", "linenumber": 1}
            elif suffix.endswith("/table"):
                payload = {"linenumber": 2}
            else:
                assert suffix.endswith(("/card/init", "/table/init"))
                payload = {}
            return httpx.Response(200, json=payload, headers=headers)

        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: real_client(
                transport=httpx.MockTransport(maconomy_response), **kwargs
            ),
        )
        response = asyncio.run(route.sync_sap_concur_invoices(AsyncMock()))
        return response, capsys.readouterr().out, create_log, create_mapping

    return run


def test_success_prints_progress_in_order_and_records_results(run_sync):
    response, output, create_log, create_mapping = run_sync()

    steps = [
        "Fetching invoices from SAP Concur",
        "Checking which invoices already exist in Maconomy",
        "Queued 1 for creation",
        "Invoice PR-1 - Checking vendor in Maconomy",
        "Invoice instance opened successfully",
        "Invoice card initialized successfully",
        "Invoice created successfully",
        "Invoice lines initialized successfully",
        "Invoice PR-1, line 1 - Checking engagement in Maconomy",
        "Invoice PR-1, line 1 - Checking task in Maconomy",
        "Invoice line created successfully",
        "Invoices: 1 created, 0 skipped, 0 failed. Invoice lines: 1 created, 0 failed.",
    ]
    positions = [output.index(step) for step in steps]
    assert positions == sorted(positions)
    assert set(response) == {"invoice_create", "lines_created", "invoices", "lines"}
    assert response["invoice_create"] and response["lines_created"]
    assert create_mapping.await_args.kwargs["allocation_lines_status"] == {"L-1": "2"}
    assert [call.kwargs["status"].value for call in create_log.await_args_list] == [
        "SUCCESS",
        "SUCCESS",
    ]


def test_existing_invoice_is_printed_and_skipped(run_sync):
    response, output, create_log, create_mapping = run_sync(existing=True)

    assert "Invoice PR-1 already exists in Maconomy. Skipping it." in output
    assert "Invoices: 0 created, 1 skipped, 0 failed" in output
    assert "Checking vendor" not in output
    assert response == {
        "invoice_create": False,
        "lines_created": False,
        "invoices": [],
        "lines": [],
    }
    assert [call.kwargs["status"].value for call in create_log.await_args_list] == [
        "SKIPPED",
        "SKIPPED",
    ]
    create_mapping.assert_not_awaited()


@pytest.mark.parametrize(
    ("failure", "reason", "missing_success"),
    [
        (
            "vendor",
            "Vendor V-1 not found in Maconomy",
            "Invoice instance opened successfully",
        ),
        ("task", "Task TASK-1 not found", "Invoice line created successfully"),
        (
            "/table/init",
            "Could not initialize invoice lines",
            "Invoice lines initialized successfully",
        ),
        (
            "/table",
            "Could not create the invoice line. The request returned HTTP 503",
            "Invoice line created successfully",
        ),
    ],
)
def test_failed_step_prints_reason_without_success(
    run_sync, failure, reason, missing_success
):
    response, output, create_log, _ = run_sync(failure=failure)

    assert reason in output
    assert missing_success not in output
    assert "fixture-only response content" not in output
    assert response["lines_created"] is False
    if failure == "vendor":
        assert response["invoices"][0]["status"] == "FAILED"
        assert create_log.await_args.kwargs["status"].value == "FAILED"
    else:
        assert response["lines"][0]["status"] == "FAILED"
        assert create_log.await_args.kwargs["status"].value == "PARTIALLY_SUCCESS"
