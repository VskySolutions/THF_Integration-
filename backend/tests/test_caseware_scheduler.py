"""Caseware follows each completed CCH scheduler attempt."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.features.schedular_services import scheduler as scheduler_module
from app.features.schedular_services.constants import (
    MACONOMY_CASEWARE_SYNC_PATH,
    MACONOMY_CCH_SYNC_PATH,
)
from app.features.schedular_services.scheduler import SchedulerService


@pytest.mark.parametrize("cch_status", [200, 404, 503])
def test_caseware_follows_completed_cch_http_attempt(cch_status: int) -> None:
    calls: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            cch_status if request.url.path == MACONOMY_CCH_SYNC_PATH else 200
        )

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://testserver",
            transport=httpx.MockTransport(handle_request),
        ) as client:
            scheduler = SchedulerService(SimpleNamespace())
            await scheduler._run_cch_caseware_sync(client)

    asyncio.run(run())
    assert calls == [MACONOMY_CCH_SYNC_PATH, MACONOMY_CASEWARE_SYNC_PATH]


def test_caseware_follows_unexpected_cch_failure(monkeypatch) -> None:
    calls: list[str] = []

    async def fail_cch(_client: object) -> bool:
        calls.append("cch")
        raise RuntimeError("CCH failed")

    async def run_caseware(_client: object) -> None:
        calls.append("caseware")

    monkeypatch.setattr(scheduler_module, "run_maconomy_cch_sync", fail_cch)
    monkeypatch.setattr(
        scheduler_module, "run_maconomy_caseware_sync", run_caseware
    )

    asyncio.run(SchedulerService(SimpleNamespace())._run_cch_caseware_sync(None))
    assert calls == ["cch", "caseware"]


def test_cycles_do_not_overlap(monkeypatch) -> None:
    calls: list[str] = []

    async def run_cch(_client: object) -> bool:
        calls.append("cch")
        await asyncio.sleep(0)
        return True

    async def run_caseware(_client: object) -> None:
        calls.append("caseware")
        await asyncio.sleep(0)

    monkeypatch.setattr(scheduler_module, "run_maconomy_cch_sync", run_cch)
    monkeypatch.setattr(
        scheduler_module, "run_maconomy_caseware_sync", run_caseware
    )

    async def run() -> None:
        scheduler = SchedulerService(SimpleNamespace())
        await asyncio.gather(
            scheduler._run_cch_caseware_sync(None),
            scheduler._run_cch_caseware_sync(None),
        )

    asyncio.run(run())
    assert calls == ["cch", "caseware", "cch", "caseware"]
