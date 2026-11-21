"""Engagement retry API: single-job lookup, conditional create, RETRY_CREATE logs."""

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from app.features.sap_concur_engagements_and_tasks_integration.constants import (
    JOBS_FILTER_FIELDS,
)
from app.features.sap_concur_engagements_and_tasks_integration.models.integration_log import (
    EngagementTaskIntegrationAction,
    EngagementTaskIntegrationStatus,
)
from app.features.sap_concur_engagements_and_tasks_integration.services import (
    retry_engagement_task_sync_service,
)
from app.features.sap_concur_engagements_and_tasks_integration.services.maconomy_services import (
    MaconomyService,
    MaconomyServiceError,
)
from app.features.sap_concur_engagements_and_tasks_integration.services.sap_concur_service import (
    SAPConcurEngagementTaskServiceError,
)


class FakeSession:
    async def commit(self) -> None:
        return None


_JOB = {
    "jobnumber": "J-1",
    "jobname": "Engagement One",
    "tasklist": "TL1",
    "name1": "Client",
}
_TASKS = [
    {"tasklist": "TL1", "taskname": "T1", "description": "Task 1"},
    {"tasklist": "TL1", "taskname": "T2", "description": "Task 2"},
]


def _maconomy(
    *,
    job: dict[str, Any] | None = _JOB,
    tasks: list[dict[str, Any]] | None = None,
    lookup_error: Exception | None = None,
    tasks_error: Exception | None = None,
):
    resolved_tasks = _TASKS if tasks is None else tasks

    class _MaconomyService:
        def __init__(self, client: object = None) -> None:
            self.client = client

        async def authenticate(self) -> None:
            return None

        async def get_engagement_by_jobnumber(self, code: str):
            if lookup_error is not None:
                raise lookup_error
            return job

        async def get_tasks_by_task_lists(self, task_lists: list[str]):
            if tasks_error is not None:
                raise tasks_error
            return resolved_tasks

    return _MaconomyService


def _concur(
    *,
    result: dict[str, Any] | None = None,
    create_error: Exception | None = None,
):
    class _ConcurService:
        calls: list[dict[str, Any]] = []

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def create_engagements_and_tasks(self, payload: dict[str, Any]):
            _ConcurService.calls.append(payload)
            if create_error is not None:
                raise create_error
            return result if result is not None else {"status": "SUCCESS"}

    _ConcurService.calls = []
    return _ConcurService


def _patch_logs(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    async def fake_create_log(session: object, **kwargs: Any) -> object:
        logs.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(
        retry_engagement_task_sync_service.integration_log_service,
        "create_log",
        fake_create_log,
    )


def _patch_mappings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing: set[tuple[str, str]] | None = None,
    created: list[tuple[str, str]] | None = None,
) -> None:
    async def fake_get_existing_pairs(session: object, jobnumbers: list[str]):
        return set(existing or set())

    async def fake_create_mapping(
        session: object, *, maconomy_jobnumber: str, maconomy_tasknumber: str
    ):
        if created is not None:
            created.append((maconomy_jobnumber, maconomy_tasknumber))
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(
        retry_engagement_task_sync_service.engagement_task_mapping_service,
        "get_existing_pairs",
        fake_get_existing_pairs,
    )
    monkeypatch.setattr(
        retry_engagement_task_sync_service.engagement_task_mapping_service,
        "create_mapping",
        fake_create_mapping,
    )


def _run(engagement_no: str = "J-1") -> dict[str, Any]:
    return asyncio.run(
        retry_engagement_task_sync_service.retry_engagement_task_sync(
            FakeSession(), engagement_no=engagement_no
        )
    )


def test_fully_unmapped_creates_engagement_and_all_tasks(
    monkeypatch,
) -> None:
    logs: list[dict[str, Any]] = []
    created: list[tuple[str, str]] = []
    concur_cls = _concur(result={"status": "SUCCESS"})
    _patch_logs(monkeypatch, logs)
    _patch_mappings(monkeypatch, created=created)
    monkeypatch.setattr(
        retry_engagement_task_sync_service, "MaconomyService", _maconomy()
    )
    monkeypatch.setattr(
        retry_engagement_task_sync_service,
        "SAPConcurEngagementTaskService",
        concur_cls,
    )

    result = _run()

    assert result["status"] == "SUCCESS"
    assert result["engagement_no"] == "J-1"
    assert result["result"]["engagements_sent"] == 1
    assert result["result"]["tasks_sent"] == 2
    assert result["result"]["engagements_created"] == 1
    assert result["result"]["tasks_created"] == 2
    assert result["result"]["concur_status"] == "SUCCESS"

    assert len(concur_cls.calls) == 1
    requests = concur_cls.calls[0]["requests"]
    assert {"shortCode": "J-1", "value": "Engagement One"} in requests
    task_entries = [r for r in requests if r.get("parentCode") == "J-1"]
    assert {r["shortCode"] for r in task_entries} == {"T1", "T2"}

    assert created == [("J-1", ""), ("J-1", "T1"), ("J-1", "T2")]
    assert len(logs) == 3
    assert all(
        log["action"] == EngagementTaskIntegrationAction.RETRY_CREATE
        for log in logs
    )
    assert all(
        log["status"] == EngagementTaskIntegrationStatus.SUCCESS
        for log in logs
    )
    assert {log["maconomy_tasknumber"] for log in logs} == {"", "T1", "T2"}


def test_fully_mapped_skips_without_concur_call(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    created: list[tuple[str, str]] = []
    concur_cls = _concur()
    _patch_logs(monkeypatch, logs)
    _patch_mappings(
        monkeypatch,
        existing={("J-1", ""), ("J-1", "T1"), ("J-1", "T2")},
        created=created,
    )
    monkeypatch.setattr(
        retry_engagement_task_sync_service, "MaconomyService", _maconomy()
    )
    monkeypatch.setattr(
        retry_engagement_task_sync_service,
        "SAPConcurEngagementTaskService",
        concur_cls,
    )

    result = _run()

    assert result["status"] == "SKIPPED"
    assert result["result"]["engagements_sent"] == 0
    assert result["result"]["tasks_sent"] == 0
    assert result["result"]["skipped_pairs"] == 3
    assert concur_cls.calls == []
    assert created == []
    assert len(logs) == 3
    assert all(
        log["status"] == EngagementTaskIntegrationStatus.SKIPPED
        for log in logs
    )
    assert all(
        log["action"] == EngagementTaskIntegrationAction.RETRY_CREATE
        for log in logs
    )
    assert {(log["maconomy_jobnumber"], log["maconomy_tasknumber"]) for log in logs} == {
        ("J-1", ""),
        ("J-1", "T1"),
        ("J-1", "T2"),
    }


def test_partial_sends_only_unmapped_task_with_include_entry_false(
    monkeypatch,
) -> None:
    logs: list[dict[str, Any]] = []
    created: list[tuple[str, str]] = []
    concur_cls = _concur(result={"status": "SUCCESS"})
    _patch_logs(monkeypatch, logs)
    _patch_mappings(
        monkeypatch,
        existing={("J-1", ""), ("J-1", "T1")},
        created=created,
    )
    monkeypatch.setattr(
        retry_engagement_task_sync_service, "MaconomyService", _maconomy()
    )
    monkeypatch.setattr(
        retry_engagement_task_sync_service,
        "SAPConcurEngagementTaskService",
        concur_cls,
    )

    result = _run()

    assert result["status"] == "SUCCESS"
    assert result["result"]["engagements_sent"] == 0
    assert result["result"]["tasks_sent"] == 1
    assert result["result"]["tasks_created"] == 1
    assert result["result"]["skipped_pairs"] == 2

    requests = concur_cls.calls[0]["requests"]
    assert len(requests) == 1
    assert requests[0]["shortCode"] == "T2"
    assert requests[0]["parentCode"] == "J-1"

    assert created == [("J-1", "T2")]
    skipped_logs = [
        log
        for log in logs
        if log["status"] == EngagementTaskIntegrationStatus.SKIPPED
    ]
    assert len(skipped_logs) == 2
    assert {
        (log["maconomy_jobnumber"], log["maconomy_tasknumber"])
        for log in skipped_logs
    } == {("J-1", ""), ("J-1", "T1")}
    success_logs = [
        log
        for log in logs
        if log["status"] == EngagementTaskIntegrationStatus.SUCCESS
    ]
    assert len(success_logs) == 1
    assert success_logs[0]["maconomy_tasknumber"] == "T2"


def test_not_found_in_maconomy_returns_404(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    _patch_logs(monkeypatch, logs)
    _patch_mappings(monkeypatch)
    monkeypatch.setattr(
        retry_engagement_task_sync_service,
        "MaconomyService",
        _maconomy(job=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        _run("MISSING-1")

    assert exc_info.value.status_code == 404
    assert len(logs) == 1
    assert logs[0]["status"] == EngagementTaskIntegrationStatus.FAILED
    assert logs[0]["action"] == EngagementTaskIntegrationAction.RETRY_CREATE
    assert logs[0]["maconomy_jobnumber"] == "MISSING-1"
    assert "not found" in logs[0]["message"]


def test_no_approved_tasks_returns_404(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    _patch_logs(monkeypatch, logs)
    _patch_mappings(monkeypatch)
    monkeypatch.setattr(
        retry_engagement_task_sync_service,
        "MaconomyService",
        _maconomy(tasks=[]),
    )

    with pytest.raises(HTTPException) as exc_info:
        _run()

    assert exc_info.value.status_code == 404
    assert len(logs) == 1
    assert logs[0]["status"] == EngagementTaskIntegrationStatus.FAILED
    assert "No approved tasks" in logs[0]["message"]


def test_maconomy_lookup_error_returns_502(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    _patch_logs(monkeypatch, logs)
    _patch_mappings(monkeypatch)
    monkeypatch.setattr(
        retry_engagement_task_sync_service,
        "MaconomyService",
        _maconomy(lookup_error=MaconomyServiceError("boom")),
    )

    with pytest.raises(HTTPException) as exc_info:
        _run()

    assert exc_info.value.status_code == 502
    assert len(logs) == 1
    assert logs[0]["status"] == EngagementTaskIntegrationStatus.FAILED
    assert "Failed to fetch engagement" in logs[0]["message"]


def test_concur_create_error_returns_200_failed(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    created: list[tuple[str, str]] = []
    _patch_logs(monkeypatch, logs)
    _patch_mappings(monkeypatch, created=created)
    monkeypatch.setattr(
        retry_engagement_task_sync_service, "MaconomyService", _maconomy()
    )
    monkeypatch.setattr(
        retry_engagement_task_sync_service,
        "SAPConcurEngagementTaskService",
        _concur(
            create_error=SAPConcurEngagementTaskServiceError("rejected")
        ),
    )

    result = _run()

    assert result["status"] == "FAILED"
    assert result["result"]["engagements_sent"] == 1
    assert result["result"]["tasks_sent"] == 2
    assert result["result"]["engagements_created"] == 0
    assert created == []
    failed_logs = [
        log
        for log in logs
        if log["status"] == EngagementTaskIntegrationStatus.FAILED
    ]
    assert len(failed_logs) == 3
    assert all(
        log["action"] == EngagementTaskIntegrationAction.RETRY_CREATE
        for log in failed_logs
    )
    assert all("creation failed" in log["message"] for log in failed_logs)


def test_concur_partial_success_splits_per_item(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    created: list[tuple[str, str]] = []
    _patch_logs(monkeypatch, logs)
    _patch_mappings(monkeypatch, created=created)
    monkeypatch.setattr(
        retry_engagement_task_sync_service, "MaconomyService", _maconomy()
    )
    monkeypatch.setattr(
        retry_engagement_task_sync_service,
        "SAPConcurEngagementTaskService",
        _concur(
            result={
                "status": "PARTIAL_SUCCESS",
                "errors": [
                    {
                        "id": "duplicate",
                        "message": "already exists",
                        "listItem": {
                            "shortCode": "T2",
                            "parentCode": "J-1",
                        },
                    }
                ],
            }
        ),
    )

    result = _run()

    assert result["status"] == "PARTIAL_SUCCESS"
    assert result["result"]["concur_status"] == "PARTIAL_SUCCESS"
    assert result["result"]["engagements_created"] == 1
    assert result["result"]["tasks_created"] == 1
    assert created == [("J-1", ""), ("J-1", "T1")]

    success_logs = [
        log
        for log in logs
        if log["status"] == EngagementTaskIntegrationStatus.SUCCESS
    ]
    failed_logs = [
        log
        for log in logs
        if log["status"] == EngagementTaskIntegrationStatus.FAILED
    ]
    assert len(success_logs) == 2
    assert len(failed_logs) == 1
    assert failed_logs[0]["maconomy_tasknumber"] == "T2"
    assert "already exists" in failed_logs[0]["message"]


def test_blank_engagement_no_returns_400() -> None:
    logs: list[dict[str, Any]] = []
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            retry_engagement_task_sync_service.retry_engagement_task_sync(
                FakeSession(), engagement_no="   "
            )
        )
    assert exc_info.value.status_code == 400
    assert logs == []


def test_job_lookup_sends_restriction_and_limit_one() -> None:
    captured: dict[str, Any] = {}

    def handle_request(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(
                204, headers={"Maconomy-Reconnect": "token-1"}
            )
        captured["path"] = request.url.path
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "panes": {
                    "filter": {
                        "meta": {"rowCount": 1, "rowOffset": 0},
                        "records": [{"data": dict(_JOB)}],
                    }
                }
            },
        )

    settings = SimpleNamespace(
        maconomy_url="http://maconomy.test",
        maconomy_shortname="shortname",
        maconomy_username="user",
        maconomy_password=SimpleNamespace(get_secret_value=lambda: "pw"),
    )

    async def run() -> dict[str, Any] | None:
        async with httpx.AsyncClient(
            base_url="http://maconomy.test",
            transport=httpx.MockTransport(handle_request),
        ) as client:
            service = MaconomyService(client, settings=settings)
            await service.authenticate()
            return await service.get_engagement_by_jobnumber("O'Brien")

    job = asyncio.run(run())

    assert captured["path"].endswith("/jobs/filter")
    assert (
        captured["json"]["restriction"]
        == "template=false and closed=false and jobnumber='O''Brien'"
    )
    assert captured["json"]["fields"] == JOBS_FILTER_FIELDS
    assert captured["json"]["limit"] == 1
    assert captured["json"]["offset"] == 0
    assert job is not None
    assert job["jobnumber"] == "J-1"


def test_job_lookup_returns_none_when_absent() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(
                204, headers={"Maconomy-Reconnect": "token-1"}
            )
        return httpx.Response(
            200,
            json={
                "panes": {
                    "filter": {
                        "meta": {"rowCount": 0, "rowOffset": 0},
                        "records": [],
                    }
                }
            },
        )

    settings = SimpleNamespace(
        maconomy_url="http://maconomy.test",
        maconomy_shortname="shortname",
        maconomy_username="user",
        maconomy_password=SimpleNamespace(get_secret_value=lambda: "pw"),
    )

    async def run() -> dict[str, Any] | None:
        async with httpx.AsyncClient(
            base_url="http://maconomy.test",
            transport=httpx.MockTransport(handle_request),
        ) as client:
            service = MaconomyService(client, settings=settings)
            await service.authenticate()
            return await service.get_engagement_by_jobnumber("MISSING-1")

    assert asyncio.run(run()) is None
