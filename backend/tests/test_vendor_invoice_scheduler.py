"""Invoice follows each completed vendor scheduler attempt."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.features.schedular_services import scheduler as scheduler_module
from app.features.schedular_services.constants import (
    SAP_CONCUR_INVOICE_SYNC_PATH,
    SAP_CONCUR_VENDOR_SYNC_PATH,
)
from app.features.schedular_services.scheduler import SchedulerService


@pytest.mark.parametrize("vendor_status", [200, 404, 503])
def test_invoice_follows_completed_vendor_http_attempt(
    vendor_status: int,
) -> None:
    calls: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            vendor_status
            if request.url.path == SAP_CONCUR_VENDOR_SYNC_PATH
            else 200
        )

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://testserver",
            transport=httpx.MockTransport(handle_request),
        ) as client:
            scheduler = SchedulerService(SimpleNamespace())
            await scheduler._run_sap_concur_vendor_invoice_sync(client)

    asyncio.run(run())
    assert calls == [SAP_CONCUR_VENDOR_SYNC_PATH, SAP_CONCUR_INVOICE_SYNC_PATH]


def test_invoice_follows_unexpected_vendor_failure(monkeypatch) -> None:
    calls: list[str] = []

    async def fail_vendor(_client: object) -> bool:
        calls.append("vendor")
        raise RuntimeError("Vendor failed")

    async def run_invoice(_client: object) -> None:
        calls.append("invoice")

    monkeypatch.setattr(
        scheduler_module, "run_sap_concur_vendor_sync", fail_vendor
    )
    monkeypatch.setattr(
        scheduler_module, "run_sap_concur_invoice_sync", run_invoice
    )

    asyncio.run(
        SchedulerService(SimpleNamespace())._run_sap_concur_vendor_invoice_sync(
            None
        )
    )
    assert calls == ["vendor", "invoice"]


def test_cycles_do_not_overlap(monkeypatch) -> None:
    calls: list[str] = []

    async def run_vendor(_client: object) -> bool:
        calls.append("vendor")
        await asyncio.sleep(0)
        return True

    async def run_invoice(_client: object) -> None:
        calls.append("invoice")
        await asyncio.sleep(0)

    monkeypatch.setattr(
        scheduler_module, "run_sap_concur_vendor_sync", run_vendor
    )
    monkeypatch.setattr(
        scheduler_module, "run_sap_concur_invoice_sync", run_invoice
    )

    async def run() -> None:
        scheduler = SchedulerService(SimpleNamespace())
        await asyncio.gather(
            scheduler._run_sap_concur_vendor_invoice_sync(None),
            scheduler._run_sap_concur_vendor_invoice_sync(None),
        )

    asyncio.run(run())
    assert calls == ["vendor", "invoice", "vendor", "invoice"]
