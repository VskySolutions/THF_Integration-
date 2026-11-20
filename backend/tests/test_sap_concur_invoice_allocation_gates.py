"""Tests for the SAP Concur invoice Maconomy presence gates.

Covers the 2026-11-18 implementations:

Reference data (one fetch per run, fail-closed):
- ``get_all_vendor_numbers`` / ``get_all_entity_names`` parsing,
  blocked/empty skipping, error wrapping, bad-shape rejection
- run aborts BEFORE any write when the reference fetch fails

jobtasks engagement/task lookup:
- fresh instance per request (instance -> data sequence + payloads)
- HTTP 204 => engagement does not exist (``None``)
- taskname set returned (casefolded), tasks printed, truncation
  tripwire at the fixed limit 100

Per-line gates (batch continues after a failure):
- Engagement / Task / Department FAILED entries with machine-readable
  ``reason`` keys; gate order Engagement -> Task -> Department
- fetch errors are not cached (retried by the next line)
- memoization: ONE jobtasks fetch per unique engagement per invoice

Run-level vendor gate:
- unknown vendor stops the invoice row (no row POST) with a message
- case-insensitive vendor match lets the row through
"""

import asyncio
import json
import re
import uuid
from collections import Counter
from typing import Any

import httpx
import pytest

from app.features.sap_concur_invoice_integration.services import (
    maconomy_invoice_service as service_module,
)
from app.features.sap_concur_invoice_integration.services.maconomy_invoice_service import (
    AllocationLineValidationError,
    MaconomyInvoiceService,
    MaconomyInvoiceServiceError,
)

CONCURRENCY_TOKEN = str(uuid.uuid4())
INSTANCE_ID = str(uuid.uuid4())

TASK_RECORDS = [
    {"data": {"taskname": "Task-1", "description": "First task"}},
    {"data": {"taskname": "Task-2", "description": "Second task"}},
]

INVOICE: dict[str, Any] = {
    "Name": "ACME Invoice",
    "InvoiceNumber": "INV-1",
    "InvoiceDate": "2026-11-01",
    "PaymentRequestId": "PR-1",
    "VendorRemitAddress": {"VendorCode": "V-404"},
}


def _line(
    engagement: str,
    task: str,
    *,
    line_id: str = "L",
    **extra: Any,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "LineItemId": line_id,
        "Custom10": engagement,
        "Custom11": task,
        "Department": "Assurance",
        "UnitPrice": "2",
    }
    item.update(extra)
    return item


class FakeMaconomy:
    """Configurable ``httpx.MockTransport`` backend for the service."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.vendors: list[str] = []
        self.entities: list[dict[str, Any]] = []
        self.reference_fail = False
        self.bad_reference_shape = False
        self.row_posts = 0
        self.alloc_row_posts = 0
        self.jt_instances = 0
        self.jt_instance_fail = False
        self.jt_data: Counter = Counter()

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        headers = {"Maconomy-Concurrency-Control": CONCURRENCY_TOKEN}

        # --- auth ---
        if path.endswith("/login"):
            return httpx.Response(204, headers={"Maconomy-Reconnect": "tok"})

        # --- reference data ---
        if path.endswith("/vendorcard/filter"):
            if self.reference_fail:
                return httpx.Response(500, text="vendor reference down")
            if self.bad_reference_shape:
                return httpx.Response(
                    200, json={"panes": {"filter": {"records": "bad"}}}
                )
            records = [
                {"data": {"vendornumber": value}}
                for value in self.vendors
            ]
            return httpx.Response(
                200,
                json={
                    "panes": {
                        "filter": {
                            "meta": {
                                "rowCount": len(records),
                                "rowOffset": 0,
                            },
                            "records": records,
                        }
                    }
                },
            )
        if path.endswith("/entities/filter"):
            if self.reference_fail:
                return httpx.Response(500, text="entity reference down")
            if self.bad_reference_shape:
                return httpx.Response(
                    200, json={"panes": {"filter": {"records": "bad"}}}
                )
            records = [{"data": entity} for entity in self.entities]
            return httpx.Response(
                200,
                json={
                    "panes": {
                        "filter": {
                            "meta": {
                                "rowCount": len(records),
                                "rowOffset": 0,
                            },
                            "records": records,
                        }
                    }
                },
            )

        # --- jobtasks (engagement + tasks) ---
        if path.endswith("/jobtasks/instances"):
            if self.jt_instance_fail:
                return httpx.Response(500, text="jobtasks instance down")
            self.jt_instances += 1
            return httpx.Response(
                200,
                json={"meta": {"containerInstanceId": INSTANCE_ID}},
                headers=headers,
            )
        match = re.search(
            r"/jobtasks/instances/[^/]+/data;jobnumber=([^/?]+)$", path
        )
        if match:
            engagement = match.group(1)
            self.jt_data[engagement] += 1
            if engagement == "GHOST":
                # User contract: 204 => engagement not in Maconomy.
                return httpx.Response(204)
            if engagement == "ERR":
                return httpx.Response(500, text="jobtasks data down")
            if engagement == "MANY":
                records = [
                    {"data": {"taskname": f"T{i}", "description": ""}}
                    for i in range(100)
                ]
                return httpx.Response(
                    200,
                    json={"panes": {"table": {"records": records}}},
                    headers=headers,
                )
            return httpx.Response(
                200,
                json={"panes": {"table": {"records": TASK_RECORDS}}},
                headers=headers,
            )

        # --- vendorinvoices (journal + rows) ---
        if path.endswith("/vendorinvoices/instances"):
            return httpx.Response(
                200,
                json={"meta": {"containerInstanceId": INSTANCE_ID}},
                headers=headers,
            )
        if "/vendorinvoices/instances/" in path:
            if path.endswith("/data/panes/card/init"):
                return httpx.Response(200, json={"data": {}}, headers=headers)
            if path.endswith("/data/panes/card"):
                return httpx.Response(
                    200,
                    json={
                        "panes": {
                            "card": {
                                "records": [
                                    {"data": {"journalnumber": "10585"}}
                                ]
                            }
                        }
                    },
                    headers=headers,
                )
            if path.endswith("/data/panes/table/init"):
                return httpx.Response(200, json={"data": {}}, headers=headers)
            if path.endswith("/data/panes/table"):
                self.row_posts += 1
                return httpx.Response(
                    200,
                    json={
                        "panes": {
                            "table": {
                                "records": [
                                    {"data": {"linenumber": 5}}
                                ]
                            }
                        }
                    },
                    headers=headers,
                )

        # --- vendorinvoiceallocation (allocation lines) ---
        if path.endswith("/vendorinvoiceallocation/instances"):
            return httpx.Response(
                200,
                json={"meta": {"containerInstanceId": INSTANCE_ID}},
                headers=headers,
            )
        if "/vendorinvoiceallocation/instances/" in path:
            if "/data;linenumber=" in path:
                return httpx.Response(200, json={}, headers=headers)
            if path.endswith("/data/panes/table/init"):
                return httpx.Response(200, json={"data": {}}, headers=headers)
            if path.endswith("/data/panes/table"):
                self.alloc_row_posts += 1
                return httpx.Response(
                    200,
                    json={
                        "panes": {
                            "table": {
                                "records": [
                                    {"data": {"linenumber": 1}}
                                ]
                            }
                        }
                    },
                    headers=headers,
                )

        return httpx.Response(500, text=f"UNMOCKED {request.method} {path}")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler), timeout=60.0
        )


@pytest.fixture
def fake() -> FakeMaconomy:
    return FakeMaconomy()


@pytest.fixture
def run_state(monkeypatch):
    """Patch httpx.AsyncClient so create_journal_with_invoices hits the
    fake backend (that method builds its own internal client)."""
    state = FakeMaconomy()
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return real_client(
            transport=httpx.MockTransport(state.handler), timeout=60.0
        )

    monkeypatch.setattr(service_module.httpx, "AsyncClient", factory)
    return state


# =====================================================================
# Reference data: get_all_vendor_numbers / get_all_entity_names
# =====================================================================
def test_vendor_numbers_stripped_and_casefolded(fake: FakeMaconomy):
    fake.vendors = ["V-77", "  ", "ABC"]

    async def run():
        async with fake.client() as client:
            return await MaconomyInvoiceService().get_all_vendor_numbers(
                client, "tok"
            )

    assert asyncio.run(run()) == {"v-77", "abc"}


def test_entity_names_skip_blocked_and_empty(fake: FakeMaconomy):
    fake.entities = [
        {"entityname": "  Assurance ", "description": "A", "blocked": False},
        {"entityname": "TAX", "description": "T", "blocked": True},
        {"entityname": "", "description": "x", "blocked": False},
    ]

    async def run():
        async with fake.client() as client:
            return await MaconomyInvoiceService().get_all_entity_names(
                client, "tok"
            )

    assert asyncio.run(run()) == {"assurance"}


def test_vendor_reference_http_error_wraps(fake: FakeMaconomy):
    fake.reference_fail = True

    async def run():
        async with fake.client() as client:
            await MaconomyInvoiceService().get_all_vendor_numbers(
                client, "tok"
            )

    with pytest.raises(
        MaconomyInvoiceServiceError, match="vendor reference request failed"
    ):
        asyncio.run(run())


def test_entity_reference_bad_shape_raises():
    def bad_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"panes": {"filter": {"records": "bad"}}}
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(bad_handler)
        ) as client:
            await MaconomyInvoiceService().get_all_entity_names(
                client, "tok"
            )

    with pytest.raises(
        MaconomyInvoiceServiceError, match="Invalid Maconomy entities"
    ):
        asyncio.run(run())


# =====================================================================
# jobtasks: get_engagement_tasks
# =====================================================================
def test_engagement_tasks_returns_casefolded_taskname_set(
    fake: FakeMaconomy,
):
    async def run():
        async with fake.client() as client:
            return await MaconomyInvoiceService().get_engagement_tasks(
                client, "tok", "E1"
            )

    assert asyncio.run(run()) == {"task-1", "task-2"}


def test_engagement_tasks_204_returns_none(fake: FakeMaconomy):
    async def run():
        async with fake.client() as client:
            return await MaconomyInvoiceService().get_engagement_tasks(
                client, "tok", "GHOST"
            )

    assert asyncio.run(run()) is None


def test_engagement_tasks_instance_error_wraps(fake: FakeMaconomy):
    fake.jt_instance_fail = True

    async def run():
        async with fake.client() as client:
            await MaconomyInvoiceService().get_engagement_tasks(
                client, "tok", "E1"
            )

    with pytest.raises(
        MaconomyInvoiceServiceError, match="jobtasks instance request failed"
    ):
        asyncio.run(run())


def test_engagement_tasks_data_error_wraps(fake: FakeMaconomy):
    async def run():
        async with fake.client() as client:
            await MaconomyInvoiceService().get_engagement_tasks(
                client, "tok", "ERR"
            )

    with pytest.raises(
        MaconomyInvoiceServiceError, match="jobtasks data request failed"
    ):
        asyncio.run(run())


def test_engagement_tasks_prints_retrieved_tasks(
    fake: FakeMaconomy, capsys: pytest.CaptureFixture
):
    async def run():
        async with fake.client() as client:
            await MaconomyInvoiceService().get_engagement_tasks(
                client, "tok", "E1"
            )

    asyncio.run(run())
    out = capsys.readouterr().out

    assert "[jobtasks] engagement 'E1': 2 task(s) retrieved" in out
    assert "Task-1" in out and "Task-2" in out


def test_engagement_tasks_204_prints_missing_engagement(
    fake: FakeMaconomy, capsys: pytest.CaptureFixture
):
    async def run():
        async with fake.client() as client:
            await MaconomyInvoiceService().get_engagement_tasks(
                client, "tok", "GHOST"
            )

    asyncio.run(run())
    out = capsys.readouterr().out

    assert "engagement does not exist in Maconomy" in out


def test_engagement_tasks_request_sequence_and_payloads(
    fake: FakeMaconomy,
):
    captured: list[httpx.Request] = []
    inner = fake.handler

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return inner(request)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(capture)
        ) as client:
            await MaconomyInvoiceService().get_engagement_tasks(
                client, "tok", "E1"
            )

    asyncio.run(run())

    # Fresh instance FIRST, then the data call (user 2026-11-18).
    assert len(captured) == 2
    instance_request, data_request = captured
    assert instance_request.url.path.endswith("/jobtasks/instances")

    instance_payload = json.loads(instance_request.content)
    assert "jobnumber" in instance_payload["panes"]["card"]["fields"]
    table_fields = instance_payload["panes"]["table"]["fields"]
    assert "taskname" in table_fields
    assert "description" in table_fields

    assert "/data;jobnumber=E1" in data_request.url.path
    assert json.loads(data_request.content) == {"limit": 100, "offset": 0}


def test_engagement_tasks_truncation_tripwire(
    fake: FakeMaconomy, capsys: pytest.CaptureFixture
):
    async def run():
        async with fake.client() as client:
            return await MaconomyInvoiceService().get_engagement_tasks(
                client, "tok", "MANY"
            )

    tasks = asyncio.run(run())

    assert len(tasks) == 100
    assert "possible truncation" in capsys.readouterr().out


# =====================================================================
# Per-line gates via _create_lines_for_invoice
# =====================================================================
async def _create_lines(
    fake: FakeMaconomy,
    line_items: list[dict[str, Any]],
    entity_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    service = MaconomyInvoiceService()
    async with fake.client() as client:
        return await service._create_lines_for_invoice(
            client=client,
            reconnect_token="tok",
            invoice_id="PR-1",
            journallinenumber=5,
            line_items=line_items,
            journalnumber="10585",
            entity_names=(
                {"assurance"} if entity_names is None else entity_names
            ),
        )


def test_engagement_missing_stops_only_that_line(fake: FakeMaconomy):
    lines = asyncio.run(
        _create_lines(
            fake,
            [
                _line("GHOST", "Task-1", line_id="L0"),
                _line("E1", "Task-1", line_id="L1"),
            ],
        )
    )

    l0, l1 = lines
    assert l0["status"] == "FAILED"
    assert l0["reason"] == "ENGAGEMENT_NOT_FOUND"
    assert "Engagement GHOST not found in Maconomy" in l0["message"]
    # Batch continues: the next line is created.
    assert l1["status"] == "SUCCESS"
    assert fake.alloc_row_posts == 1
    assert fake.jt_data["GHOST"] == 1
    assert fake.jt_data["E1"] == 1


def test_task_missing_fails_with_reason(fake: FakeMaconomy):
    lines = asyncio.run(_create_lines(fake, [_line("E1", "Task-X")]))

    entry = lines[0]
    assert entry["status"] == "FAILED"
    assert entry["reason"] == "TASK_NOT_FOUND"
    assert (
        "Task Task-X not found in Maconomy for engagement E1"
        in entry["message"]
    )
    assert fake.alloc_row_posts == 0


def test_engagement_and_task_present_creates_line(fake: FakeMaconomy):
    lines = asyncio.run(_create_lines(fake, [_line("E1", "Task-1")]))

    assert lines[0]["status"] == "SUCCESS"
    assert fake.alloc_row_posts == 1
    assert fake.jt_data["E1"] == 1


def test_department_missing_fails_with_reason(fake: FakeMaconomy):
    lines = asyncio.run(
        _create_lines(fake, [_line("E1", "Task-1")], entity_names=set())
    )

    entry = lines[0]
    assert entry["status"] == "FAILED"
    assert entry["reason"] == "DEPARTMENT_NOT_FOUND"
    assert "Department Assurance not found in Maconomy" in entry["message"]
    assert fake.alloc_row_posts == 0


def test_gate_order_engagement_before_department(fake: FakeMaconomy):
    lines = asyncio.run(
        _create_lines(
            fake,
            [_line("GHOST", "Task-1")],
            entity_names=set(),
        )
    )

    assert lines[0]["reason"] == "ENGAGEMENT_NOT_FOUND"


def test_gate_order_task_before_department(fake: FakeMaconomy):
    lines = asyncio.run(
        _create_lines(
            fake,
            [_line("E1", "Task-X")],
            entity_names=set(),
        )
    )

    assert lines[0]["reason"] == "TASK_NOT_FOUND"


def test_fetch_error_not_cached_retried_by_next_line(fake: FakeMaconomy):
    lines = asyncio.run(
        _create_lines(
            fake,
            [
                _line("ERR", "Task-1", line_id="L0"),
                _line("ERR", "Task-1", line_id="L1"),
                _line("E1", "Task-1", line_id="L2"),
            ],
        )
    )

    l0, l1, l2 = lines
    # Fetch errors carry no reason (not a "does not exist" verdict)...
    assert l0["status"] == "FAILED" and "reason" not in l0
    assert "jobtasks data request failed" in l0["message"]
    assert l1["status"] == "FAILED" and "reason" not in l1
    # ...are NOT cached -> the second line retries the fetch...
    assert fake.jt_data["ERR"] == 2
    # ...and the batch continues with the next engagement.
    assert l2["status"] == "SUCCESS"


def test_memo_one_fetch_per_unique_engagement(fake: FakeMaconomy):
    lines = asyncio.run(
        _create_lines(
            fake,
            [
                _line("E1", "Task-1", line_id="L0"),
                _line("E1", "Task-2", line_id="L1"),
            ],
        )
    )

    assert all(entry["status"] == "SUCCESS" for entry in lines)
    assert fake.jt_instances == 1
    assert sum(fake.jt_data.values()) == 1


def test_empty_engagement_skips_gate_and_mapper_raises(
    fake: FakeMaconomy,
):
    lines = asyncio.run(
        _create_lines(fake, [_line("", "Task-1")])
    )

    entry = lines[0]
    assert entry["status"] == "FAILED"
    # Required-field failure, not an existence verdict.
    assert "reason" not in entry
    assert "Missing required" in entry["message"]
    assert fake.jt_instances == 0


def test_allocation_line_validation_error_carries_reason():
    exc = AllocationLineValidationError("boom", "ENGAGEMENT_NOT_FOUND")

    assert isinstance(exc, ValueError)
    assert exc.reason == "ENGAGEMENT_NOT_FOUND"
    assert str(exc) == "boom"


# =====================================================================
# Run-level: vendor gate + fail-closed reference fetch
# =====================================================================
def _invoice(vendor_code: str) -> dict[str, Any]:
    return dict(
        INVOICE, VendorRemitAddress={"VendorCode": vendor_code}
    )


def _run_journal(
    state: FakeMaconomy, entries: list[dict[str, Any]]
) -> dict[str, Any]:
    service = MaconomyInvoiceService()
    return asyncio.run(service.create_journal_with_invoices(entries=entries))


def test_vendor_missing_stops_invoice_row(run_state: FakeMaconomy):
    run_state.vendors = ["V-100"]
    run_state.entities = [{"entityname": "Assurance", "blocked": False}]

    result = _run_journal(
        run_state,
        [{"invoice": _invoice("V-404"), "lineItems": []}],
    )

    entry = result["invoices"][0]
    assert entry["status"] == "FAILED"
    assert "Vendor V-404 not found in Maconomy" in entry["message"]
    # No row POST for the stopped invoice.
    assert run_state.row_posts == 0


def test_vendor_present_case_insensitive_creates_row(
    run_state: FakeMaconomy,
):
    run_state.vendors = ["v-77"]
    run_state.entities = [{"entityname": "Assurance", "blocked": False}]

    result = _run_journal(
        run_state,
        [{"invoice": _invoice("V-77"), "lineItems": []}],
    )

    entry = result["invoices"][0]
    assert entry["status"] == "SUCCESS"
    assert entry["journallinenumber"] == 5
    assert run_state.row_posts == 1


def test_reference_fetch_failure_aborts_before_any_write(
    run_state: FakeMaconomy,
):
    run_state.reference_fail = True

    with pytest.raises(
        MaconomyInvoiceServiceError, match="reference request failed"
    ):
        _run_journal(
            run_state,
            [{"invoice": _invoice("V-77"), "lineItems": []}],
        )

    # Fail-closed: nothing was written (no journal, no row).
    assert run_state.row_posts == 0
    assert run_state.jt_instances == 0


def test_validation_failures_shape_for_router_jsonb(
    run_state: FakeMaconomy,
):
    run_state.vendors = ["V-77"]
    run_state.entities = [{"entityname": "Assurance", "blocked": False}]

    result = _run_journal(
        run_state,
        [
            {
                "invoice": _invoice("V-77"),
                "lineItems": [
                    _line("GHOST", "Task-1", line_id="L0"),
                    _line("E1", "Task-X", line_id="L1"),
                ],
            }
        ],
    )

    # Same comprehension the router applies into the per-invoice
    # details JSONB (one DB row per invoice).
    validation_failures = [
        {
            "line_index": entry.get("line_index"),
            "reason": entry.get("reason"),
            "message": entry.get("message"),
        }
        for entry in result["lines"]
        if entry.get("reason")
    ]

    assert [failure["reason"] for failure in validation_failures] == [
        "ENGAGEMENT_NOT_FOUND",
        "TASK_NOT_FOUND",
    ]
    assert validation_failures[0]["line_index"] == 0
    assert validation_failures[1]["line_index"] == 1
    # The invoice row itself survived (vendor gate passed).
    assert result["invoices"][0]["status"] == "SUCCESS"
