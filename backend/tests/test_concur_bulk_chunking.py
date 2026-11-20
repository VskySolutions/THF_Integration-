"""Concur bulk chunking: <=250 requests per POST, sequential chunks, aggregation."""

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.features.sap_concur_engagements_and_tasks_integration.services import (
    engagement_task_mapping_service,
    integration_log_service,
)
from app.features.sap_concur_engagements_and_tasks_integration.services.sap_concur_service import (
    SAPConcurEngagementTaskService,
    SAPConcurEngagementTaskServiceError,
)

_BULK_URL = "https://concur.example/list/v4/lists/LIST1/bulk"


def _settings(list_id: str = "LIST1") -> SimpleNamespace:
    return SimpleNamespace(
        sap_engagement_list_id=list_id,
        sap_concur_api_base_url="https://concur.example",
    )


def _resp(
    status_code: int = 200,
    *,
    json_body: dict[str, Any] | None = None,
    text: str = "",
) -> httpx.Response:
    request = httpx.Request("POST", _BULK_URL)
    if json_body is not None:
        return httpx.Response(status_code, json=json_body, request=request)
    return httpx.Response(status_code, text=text, request=request)


def _requests(count: int) -> list[dict[str, str]]:
    return [
        {"shortCode": f"E{index}", "value": f"Engagement {index}"}
        for index in range(count)
    ]


def _patch_concur(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[httpx.Response],
) -> list[dict[str, Any]]:
    """Script _request_with_auth responses; return the captured payloads."""
    calls: list[dict[str, Any]] = []

    async def fake_request(
        self: object,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        payload = kwargs.get("json") or {}
        calls.append(payload)
        index = min(len(calls) - 1, len(outcomes) - 1)
        return outcomes[index]

    monkeypatch.setattr(
        SAPConcurEngagementTaskService, "_request_with_auth", fake_request
    )
    return calls


def _run(payload: dict[str, Any], settings: SimpleNamespace | None = None):
    service = SAPConcurEngagementTaskService(settings=settings or _settings())
    return asyncio.run(service.create_engagements_and_tasks(payload))


# --- splitting ---------------------------------------------------------


def test_split_250_is_single_request(monkeypatch) -> None:
    body = {"status": "SUCCESS"}
    calls = _patch_concur(monkeypatch, [_resp(json_body=body)])

    result = _run({"requests": _requests(250)})

    assert [len(call["requests"]) for call in calls] == [250]
    # Single chunk: Concur's body returned verbatim (no wrapper keys).
    assert result == body
    assert "chunk_count" not in result


def test_split_251_two_chunks(monkeypatch) -> None:
    calls = _patch_concur(
        monkeypatch,
        [
            _resp(json_body={"status": "SUCCESS"}),
            _resp(json_body={"status": "SUCCESS"}),
        ],
    )

    _run({"requests": _requests(251)})

    assert [len(call["requests"]) for call in calls] == [250, 1]


def test_split_500_two_equal_chunks(monkeypatch) -> None:
    calls = _patch_concur(
        monkeypatch,
        [
            _resp(json_body={"status": "SUCCESS"}),
            _resp(json_body={"status": "SUCCESS"}),
        ],
    )

    _run({"requests": _requests(500)})

    assert [len(call["requests"]) for call in calls] == [250, 250]


def test_split_600_three_chunks(monkeypatch) -> None:
    calls = _patch_concur(
        monkeypatch,
        [
            _resp(json_body={"status": "SUCCESS"}),
            _resp(json_body={"status": "SUCCESS"}),
            _resp(json_body={"status": "SUCCESS"}),
        ],
    )

    _run({"requests": _requests(600)})

    assert [len(call["requests"]) for call in calls] == [250, 250, 100]


def test_empty_requests_raises() -> None:
    with pytest.raises(SAPConcurEngagementTaskServiceError, match="No engagement"):
        _run({"requests": []})


def test_missing_list_id_raises() -> None:
    with pytest.raises(SAPConcurEngagementTaskServiceError, match="list id"):
        _run({"requests": _requests(1)}, settings=_settings(list_id="  "))


# --- single-chunk regression -------------------------------------------


def test_single_chunk_http_error_raises_with_status(monkeypatch) -> None:
    _patch_concur(
        monkeypatch,
        [_resp(400, text='{"error":{"message":"bad request"}}')],
    )

    with pytest.raises(
        SAPConcurEngagementTaskServiceError, match="400"
    ):
        _run({"requests": _requests(10)})


def test_single_chunk_verbatim_body(monkeypatch) -> None:
    body = {"status": "PARTIAL_SUCCESS", "errors": [], "extra": True}
    _patch_concur(monkeypatch, [_resp(json_body=body)])

    result = _run({"requests": _requests(10)})

    assert result == body


# --- multi-chunk aggregation -------------------------------------------


def test_multi_chunk_all_success(monkeypatch) -> None:
    calls = _patch_concur(
        monkeypatch,
        [
            _resp(json_body={"status": "SUCCESS"}),
            _resp(json_body={"status": "SUCCESS"}),
        ],
    )

    result = _run({"requests": _requests(500)})

    assert len(calls) == 2
    assert result["status"] == "SUCCESS"
    assert result["chunk_count"] == 2
    assert result["errors"] == []


def test_multi_chunk_partial_errors_merged(monkeypatch) -> None:
    concur_error = {
        "id": "duplicate",
        "message": "already exists",
        "listItem": {"shortCode": "E300"},
    }
    _patch_concur(
        monkeypatch,
        [
            _resp(json_body={"status": "SUCCESS"}),
            _resp(
                json_body={
                    "status": "PARTIAL_SUCCESS",
                    "errors": [concur_error],
                }
            ),
        ],
    )

    result = _run({"requests": _requests(500)})

    assert result["status"] == "PARTIAL_SUCCESS"
    assert result["chunk_count"] == 2
    assert concur_error in result["errors"]


def test_chunk_2_http_failure_continues_remaining_chunks(monkeypatch) -> None:
    calls = _patch_concur(
        monkeypatch,
        [
            _resp(json_body={"status": "SUCCESS"}),
            _resp(400, text='{"error":{"message":"boom"}}'),
            _resp(json_body={"status": "SUCCESS"}),
        ],
    )

    result = _run({"requests": _requests(600)})

    # Fail-fast would have stopped after chunk 2; we attempt all three.
    assert len(calls) == 3
    assert [len(call["requests"]) for call in calls] == [250, 250, 100]

    assert result["status"] == "PARTIAL_SUCCESS"
    assert result["chunk_count"] == 3

    # Synthesized errors cover exactly chunk 2's items (E250..E499).
    synthesized = [
        error for error in result["errors"] if error.get("id") == "chunk.failed"
    ]
    assert len(synthesized) == 250
    short_codes = {
        error["listItem"]["shortCode"] for error in synthesized
    }
    assert short_codes == {f"E{index}" for index in range(250, 500)}
    assert all("400" in error["message"] for error in synthesized)


def test_aggregate_synthesizes_parent_code_for_tasks() -> None:
    # 4 requests fit in one chunk, so exercise aggregation directly.
    good = [{"status": "SUCCESS"}]
    bad = [
        (
            [
                {"shortCode": "E1", "value": "Engagement 1"},
                {"shortCode": "T2", "value": "Task 2", "parentCode": "E1"},
                {"shortCode": "T3", "value": "Task 3", "parentCode": "E1"},
            ],
            "SAP Concur bulk list request failed: 500 server error",
        )
    ]

    result = SAPConcurEngagementTaskService._aggregate_chunk_results(
        good, bad, 2
    )

    assert result["status"] == "PARTIAL_SUCCESS"
    assert result["chunk_count"] == 2
    synthesized = [
        error for error in result["errors"] if error.get("id") == "chunk.failed"
    ]
    assert len(synthesized) == 3
    by_code = {
        error["listItem"]["shortCode"]: error["listItem"]
        for error in synthesized
    }
    # Parent entry: shortCode only (router keys it as an engagement).
    assert by_code["E1"] == {"shortCode": "E1"}
    # Task entries keep parentCode so the router keys them as tasks.
    assert by_code["T2"] == {"shortCode": "T2", "parentCode": "E1"}
    assert by_code["T3"] == {"shortCode": "T3", "parentCode": "E1"}


def test_all_chunks_fail_raises(monkeypatch) -> None:
    calls = _patch_concur(
        monkeypatch,
        [
            _resp(400, text="first"),
            _resp(400, text="second"),
        ],
    )

    with pytest.raises(
        SAPConcurEngagementTaskServiceError, match="All 2 SAP Concur bulk chunks failed"
    ):
        _run({"requests": _requests(500)})

    assert len(calls) == 2


def test_chunk_order_preserved(monkeypatch) -> None:
    requests = _requests(600)
    calls = _patch_concur(
        monkeypatch,
        [
            _resp(json_body={"status": "SUCCESS"}),
            _resp(json_body={"status": "SUCCESS"}),
            _resp(json_body={"status": "SUCCESS"}),
        ],
    )

    _run({"requests": requests})

    flattened = [
        item for call in calls for item in call["requests"]
    ]
    assert flattened == requests


# --- router integration ------------------------------------------------


class _FakeSession:
    async def commit(self) -> None:
        return None


def _patch_router_stack(
    monkeypatch: pytest.MonkeyPatch,
    router_module: Any,
    sap_concur_service: Any,
    *,
    existing_pairs: set[tuple[str, str]],
    logs: list[dict[str, Any]],
    mappings: list[tuple[str, str]],
    outcomes: list[httpx.Response],
) -> list[dict[str, Any]]:
    class _FakeMaconomyService:
        def __init__(self, client: object = None) -> None:
            self.client = client

        async def authenticate(self) -> None:
            return None

        async def get_engagements(self, *, limit: int, offset: int):
            return [
                {
                    "jobnumber": "E1",
                    "jobname": "Engagement One",
                    "tasklist": "TL1",
                    "name1": "Client",
                },
                {
                    "jobnumber": "E2",
                    "jobname": "Engagement Two",
                    "tasklist": "TL2",
                    "name1": "Client",
                },
            ]

        async def get_tasks_by_task_lists(self, task_lists: list[str]):
            tasks = [
                {
                    "tasklist": "TL1",
                    "taskname": f"T{index}",
                    "description": f"Task {index}",
                }
                # T1..T249 (249 tasks on engagement E1)
                for index in range(1, 250)
            ]
            tasks.extend(
                {
                    "tasklist": "TL2",
                    "taskname": f"U{index}",
                    "description": f"Task U{index}",
                }
                # U1..U4 (4 tasks on engagement E2)
                for index in range(1, 5)
            )
            return tasks

    async def fake_get_existing_pairs(session: object, jobnumbers: list[str]):
        return set(existing_pairs)

    async def fake_create_mapping(
        session: object, *, maconomy_jobnumber: str, maconomy_tasknumber: str
    ):
        pair = (maconomy_jobnumber, maconomy_tasknumber)
        mappings.append(pair)
        return SimpleNamespace(id=uuid.uuid4())

    async def fake_create_log(session: object, **kwargs: Any) -> object:
        logs.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(router_module, "MaconomyService", _FakeMaconomyService)
    monkeypatch.setattr(
        engagement_task_mapping_service,
        "get_existing_pairs",
        fake_get_existing_pairs,
    )
    monkeypatch.setattr(
        engagement_task_mapping_service,
        "create_mapping",
        fake_create_mapping,
    )
    monkeypatch.setattr(
        integration_log_service, "create_log", fake_create_log
    )
    monkeypatch.setattr(sap_concur_service, "get_settings", lambda: _settings())
    return _patch_concur(monkeypatch, outcomes)


def test_router_two_chunk_run_chunk2_failure(monkeypatch) -> None:
    from app.features.sap_concur_engagements_and_tasks_integration.routers import (
        sap_concur_engagements_and_tasks as router_module,
    )
    from app.features.sap_concur_engagements_and_tasks_integration.services import (
        sap_concur_service as sap_concur_service,
    )
    from app.features.sap_concur_engagements_and_tasks_integration.models.integration_log import (
        EngagementTaskIntegrationAction,
        EngagementTaskIntegrationStatus,
    )

    logs: list[dict[str, Any]] = []
    mappings: list[tuple[str, str]] = []
    calls = _patch_router_stack(
        monkeypatch,
        router_module,
        sap_concur_service,
        # E1/T1 pre-mapped -> SKIPPED; not sent to Concur.
        existing_pairs={("E1", "T1")},
        logs=logs,
        mappings=mappings,
        outcomes=[
            _resp(json_body={"status": "SUCCESS"}),
            _resp(400, text='{"error":{"message":"boom"}}'),
        ],
    )

    result = asyncio.run(
        router_module.sync_engagements_and_tasks(_FakeSession())
    )

    # 2 engagements + 248 selected E1 tasks + 4 E2 tasks = 254 -> [250, 4].
    assert len(calls) == 2
    assert [len(call["requests"]) for call in calls] == [250, 4]

    assert result["status"] == "PARTIAL_SUCCESS"
    assert result["chunk_count"] == 2

    skipped = [
        log for log in logs if log["status"] == EngagementTaskIntegrationStatus.SKIPPED
    ]
    assert len(skipped) == 1
    assert skipped[0]["maconomy_tasknumber"] == "T1"
    assert skipped[0]["action"] == EngagementTaskIntegrationAction.CREATE

    success = [
        log for log in logs if log["status"] == EngagementTaskIntegrationStatus.SUCCESS
    ]
    failed = [
        log for log in logs if log["status"] == EngagementTaskIntegrationStatus.FAILED
    ]
    # Chunk 1: E1, E2 + T2..T249 -> 250 successes.
    assert len(success) == 250
    # Chunk 2: U1..U4 -> 4 failures, attributed via synthesized errors.
    assert len(failed) == 4
    assert {log["maconomy_tasknumber"] for log in failed} == {
        "U1",
        "U2",
        "U3",
        "U4",
    }
    assert all("chunk.failed" in log["message"] for log in failed)

    # Mappings only for successful items: 2 engagements + 248 tasks.
    assert len(mappings) == 250
    assert ("E1", "") in mappings
    assert ("E2", "") in mappings
    assert ("E1", "T1") not in mappings
    assert all(pair[1] != "T1" for pair in mappings)
    assert not any(pair[0] == "E2" and pair[1] for pair in mappings)

    assert all(
        log["action"] == EngagementTaskIntegrationAction.CREATE
        for log in logs
    )
