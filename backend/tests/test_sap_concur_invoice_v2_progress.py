"""Verify v2 console progress alongside the sync results and database writes."""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from app.features.sap_concur_invoice_integration_v2.routers import sap_concur_invoices
from app.features.sap_concur_invoice_integration_v2.schemas.sap_concur_invoices import (
    RetryInvoiceSyncRequest,
)


SUBMIT_PATH = "/data/panes/card/0/action;name=submitforapproval"
APPROVE_PATH = "/data/panes/card/0/action;name=approveforposting"


@pytest.fixture
def run_sync(monkeypatch, capsys):
    route = sap_concur_invoices
    create_log = AsyncMock()
    create_mapping = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr(route.integration_log_service, "create_log", create_log)
    monkeypatch.setattr(route.invoice_mapping_service, "create_mapping", create_mapping)
    real_client = httpx.AsyncClient

    def run(
        failure=None,
        existing=False,
        *,
        retry=False,
        batch=False,
        line_count=1,
        requests=None,
    ):
        invoice_ids = ["PR-1", "PR-2"] if batch else ["PR-1"]

        def invoice_details(invoice_id):
            return {
                "invoice": {
                    "Name": "Test invoice",
                    "InvoiceNumber": "INV-1",
                    "InvoiceDate": "2026-11-01",
                    "PaymentRequestId": invoice_id,
                    "VendorCode": "V-1",
                },
                "lineItems": [
                    {
                        "LineItemId": f"L-{index + 1}",
                        "Engagement": "ENG-1",
                        "Task": "TASK-1",
                        "Department": "Assurance",
                        "UnitPrice": "2",
                    }
                    for index in range(line_count)
                ],
            }

        monkeypatch.setattr(
            route.SAPConcurInvoiceService,
            "get_all_invoice_digests",
            AsyncMock(
                return_value=[
                    {"PaymentRequestId": invoice_id} for invoice_id in invoice_ids
                ]
            ),
        )
        monkeypatch.setattr(
            route.SAPConcurInvoiceService,
            "get_invoice_details",
            AsyncMock(side_effect=invoice_details),
        )
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

        instances_opened = 0

        def maconomy_response(request):
            nonlocal instances_opened
            suffix = request.url.path.split("/instances", 1)[1]
            token = str(uuid.uuid4())
            if not suffix:
                instances_opened += 1
                payload = {"meta": {"containerInstanceId": str(uuid.uuid4())}}
            elif suffix.endswith("/card"):
                payload = {"journalnumber": "J-1", "linenumber": 1}
            elif suffix.endswith("/table"):
                payload = {"linenumber": 2}
            else:
                assert suffix.endswith(
                    ("/card/init", "/table/init", SUBMIT_PATH, APPROVE_PATH)
                )
                payload = {}
            if instances_opened == 1:
                if failure == "submit-token" and suffix.endswith(SUBMIT_PATH):
                    token = None
                elif failure == "allocation-token" and suffix.endswith("/table"):
                    token = None
            if requests is not None:
                requests.append((request, token))
            if instances_opened == 1:
                if failure == "submit-timeout" and suffix.endswith(SUBMIT_PATH):
                    raise httpx.ReadTimeout("fixture-only timeout", request=request)
                if failure and suffix.endswith(failure):
                    return httpx.Response(503, text="fixture-only response content")
            headers = {"Maconomy-Concurrency-Control": token} if token else {}
            if suffix.endswith(APPROVE_PATH):
                return httpx.Response(204, headers=headers)
            return httpx.Response(200, json=payload, headers=headers)

        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: real_client(
                transport=httpx.MockTransport(maconomy_response), **kwargs
            ),
        )
        if retry:
            response = asyncio.run(
                route.retry_invoice_sync(
                    AsyncMock(), RetryInvoiceSyncRequest(invoice_id="PR-1")
                )
            )
        else:
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


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("line_count", [0, 2])
def test_invoice_actions_use_same_instance_and_latest_token(
    run_sync, retry, line_count
):
    requests = []
    response, _, create_log, create_mapping = run_sync(
        retry=retry, line_count=line_count, requests=requests
    )
    instance_url = requests[1][0].url.path.removesuffix("/data/panes/card/init")
    expected_paths = ["/data/panes/card/init", "/data/panes/card"]
    if line_count:
        expected_paths += ["/data/panes/table/init"] + [
            "/data/panes/table"
        ] * line_count
    expected_paths += [SUBMIT_PATH, APPROVE_PATH]
    assert [request.url.path for request, _ in requests[1:]] == [
        f"{instance_url}{path}" for path in expected_paths
    ]
    for (request, _), (_, previous_token) in zip(
        requests[1:], requests[:-1], strict=True
    ):
        assert request.method == "POST"
        assert request.headers["Maconomy-Concurrency-Control"] == previous_token
    for request, _ in requests[-2:]:
        assert request.headers["Authorization"] == "X-Reconnect test"
        assert json.loads(request.content) == {"offset": 0, "limit": 100}

    invoice = response["invoice"] if retry else response["invoices"][0]
    assert invoice["status"] == "SUCCESS"
    assert invoice["submission"]["status"] == invoice["approval"]["status"] == "SUCCESS"
    assert create_mapping.await_args.kwargs["is_submitted"] == "SUCCESS"
    assert create_mapping.await_args.kwargs["is_approved"] == "SUCCESS"
    assert create_log.await_args.kwargs["status"] == "SUCCESS"
    assert create_log.await_args.kwargs["processing_stage"] == "COMPLETED"


@pytest.mark.parametrize(
    ("failure", "stage", "submitted", "approved", "action_paths"),
    [
        ("/card", "INVOICE_CREATION", "SKIPPED", "SKIPPED", []),
        ("/table/init", "LINE_CREATION", "SKIPPED", "SKIPPED", []),
        ("/table", "LINE_CREATION", "SKIPPED", "SKIPPED", []),
        ("task", "LINE_CREATION", "SKIPPED", "SKIPPED", []),
        ("allocation-token", "SUBMISSION", "FAILED", "SKIPPED", []),
        (SUBMIT_PATH, "SUBMISSION", "FAILED", "SKIPPED", [SUBMIT_PATH]),
        ("submit-timeout", "SUBMISSION", "FAILED", "SKIPPED", [SUBMIT_PATH]),
        ("submit-token", "APPROVAL", "SUCCESS", "FAILED", [SUBMIT_PATH]),
        (APPROVE_PATH, "APPROVAL", "SUCCESS", "FAILED", [SUBMIT_PATH, APPROVE_PATH]),
    ],
)
@pytest.mark.parametrize("retry", [False, True])
def test_invoice_action_failures_preserve_creation_results(
    run_sync, failure, stage, submitted, approved, action_paths, retry
):
    requests = []
    response, _, create_log, create_mapping = run_sync(
        failure, retry=retry, requests=requests
    )
    assert [
        f"/data/panes{request.url.path.split('/data/panes', 1)[1]}"
        for request, _ in requests
        if "/action;name=" in request.url.path
    ] == action_paths

    invoice = response["invoice"] if retry else response["invoices"][0]
    expected_status = "FAILED" if stage == "INVOICE_CREATION" else "PARTIALLY_SUCCESS"
    invoice_log = create_log.await_args_list[0].kwargs
    assert invoice_log["status"] == expected_status
    assert invoice_log["processing_stage"] == stage
    assert invoice["submission"]["status"] == submitted
    assert invoice["approval"]["status"] == approved
    assert invoice_log["details"]["submission"] == invoice["submission"]
    assert invoice_log["details"]["approval"] == invoice["approval"]
    assert "fixture-only" not in invoice_log["message"]
    if retry:
        assert response["status"] == expected_status
    else:
        assert create_log.await_args.kwargs["status"] == expected_status
        assert create_log.await_args.kwargs["processing_stage"] == stage
    if stage == "INVOICE_CREATION":
        create_mapping.assert_not_awaited()
    else:
        assert invoice["status"] == "SUCCESS"
        assert create_mapping.await_args.kwargs["is_submitted"] == submitted
        assert create_mapping.await_args.kwargs["is_approved"] == approved
    if stage in {"SUBMISSION", "APPROVAL"}:
        assert response["lines"][0]["status"] == "SUCCESS"
        if not retry:
            assert response["invoice_create"] and response["lines_created"]


def test_invoice_batch_continues_after_action_failure(run_sync):
    response, _, create_log, _ = run_sync(APPROVE_PATH, batch=True)

    assert [invoice["approval"]["status"] for invoice in response["invoices"]] == [
        "FAILED",
        "SUCCESS",
    ]
    batch_log = create_log.await_args.kwargs
    assert batch_log["status"] == "PARTIALLY_SUCCESS"
    assert batch_log["processing_stage"] == "APPROVAL"
    assert batch_log["details"]["submitted_invoices"] == 2
    assert batch_log["details"]["approved_invoices"] == 1


@pytest.mark.parametrize("retry", [False, True])
def test_existing_invoice_skips_both_actions(run_sync, retry):
    requests = []
    _, _, create_log, create_mapping = run_sync(
        existing=True, retry=retry, requests=requests
    )

    assert requests == []
    assert create_log.await_args.kwargs["status"] == "SKIPPED"
    create_mapping.assert_not_awaited()
