"""Vendor retry API: single-vendor lookup, conditional create, RETRY_CREATE logs."""

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from app.features.sap_concur_vendor_integration.models.integration_log import (
    VendorIntegrationAction,
    VendorIntegrationStatus,
)
from app.features.sap_concur_vendor_integration.services import (
    retry_vendor_sync_service,
)
from app.features.sap_concur_vendor_integration.services.maconomy_services import (
    MaconomyService,
    MaconomyServiceError,
)
from app.features.sap_concur_vendor_integration.services.sap_concur_services import (
    SAPConcurVendorServiceError,
)


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _concur_returning(result: dict[str, Any] | None):
    class _ConcurService:
        async def get_vendor_by_code(self, vendor_code: str):
            return result

    return _ConcurService


def _concur_raising(exc: Exception):
    class _ConcurService:
        async def get_vendor_by_code(self, vendor_code: str):
            raise exc

    return _ConcurService


def _maconomy(
    *,
    existing: dict[str, Any] | None = None,
    created: dict[str, Any] | None = None,
    create_error: Exception | None = None,
    lookup_error: Exception | None = None,
):
    class _MaconomyService:
        def __init__(self, client: object = None) -> None:
            self.client = client
            self.created_calls: list[dict[str, Any]] = []

        async def authenticate(self) -> None:
            return None

        async def get_vendor_by_code(self, vendor_code: str):
            if lookup_error is not None:
                raise lookup_error
            return existing

        async def create_vendor(self, sap_vendor: dict[str, Any]):
            if create_error is not None:
                raise create_error
            self.created_calls.append(sap_vendor)
            return created or {"vendornumber": "NEW-1"}

    return _MaconomyService


def _patch_logs(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    async def fake_create_log(session: object, **kwargs: Any) -> object:
        logs.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(
        retry_vendor_sync_service.integration_log_service,
        "create_log",
        fake_create_log,
    )


def _patch_mapping(
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing_mapping: object = None,
    created_mappings: list[tuple[str, str]] | None = None,
) -> None:
    async def fake_get_by_sap_code(session: object, code: str):
        return existing_mapping

    async def fake_create_mapping(
        session: object, *, sap_concur_vendor_code: str, maconomy_vendor_code: str
    ):
        if created_mappings is not None:
            created_mappings.append((sap_concur_vendor_code, maconomy_vendor_code))
        return SimpleNamespace(
            id=uuid.uuid4(), maconomy_vendor_code=maconomy_vendor_code
        )

    monkeypatch.setattr(
        retry_vendor_sync_service.vendor_mapping_service,
        "get_by_sap_code",
        fake_get_by_sap_code,
    )
    monkeypatch.setattr(
        retry_vendor_sync_service.vendor_mapping_service,
        "create_mapping",
        fake_create_mapping,
    )


def test_creates_vendor_when_missing(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    created_mappings: list[tuple[str, str]] = []
    _patch_logs(monkeypatch, logs)
    _patch_mapping(monkeypatch, created_mappings=created_mappings)
    monkeypatch.setattr(
        retry_vendor_sync_service,
        "SAPConcurVendorService",
        _concur_returning({"VendorCode": "4029-0", "VendorName": "Acme"}),
    )
    monkeypatch.setattr(
        retry_vendor_sync_service,
        "MaconomyService",
        _maconomy(existing=None, created={"vendornumber": "4029-0"}),
    )

    result = asyncio.run(
        retry_vendor_sync_service.retry_vendor_sync(
            FakeSession(), vendor_code=" 4029-0 "
        )
    )

    assert result["status"] == "SUCCESS"
    assert result["result"]["created"] is True
    assert result["result"]["maconomy_vendor_code"] == "4029-0"
    assert created_mappings == [("4029-0", "4029-0")]
    assert len(logs) == 1
    assert logs[0]["status"] == VendorIntegrationStatus.SUCCESS
    assert logs[0]["action"] == VendorIntegrationAction.RETRY_CREATE
    assert logs[0]["sap_concur_vendor_code"] == "4029-0"
    assert logs[0]["maconomy_vendor_code"] == "4029-0"


def test_skips_when_vendor_exists(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    created_mappings: list[tuple[str, str]] = []
    _patch_logs(monkeypatch, logs)
    _patch_mapping(monkeypatch, created_mappings=created_mappings)

    maconomy_cls = _maconomy(existing={"vendornumber": "4029-0", "name1": "Acme"})
    monkeypatch.setattr(
        retry_vendor_sync_service,
        "SAPConcurVendorService",
        _concur_returning({"VendorCode": "4029-0", "VendorName": "Acme"}),
    )
    monkeypatch.setattr(
        retry_vendor_sync_service, "MaconomyService", maconomy_cls
    )

    result = asyncio.run(
        retry_vendor_sync_service.retry_vendor_sync(
            FakeSession(), vendor_code="4029-0"
        )
    )

    assert result["status"] == "SKIPPED"
    assert result["result"]["created"] is False
    assert created_mappings == []
    assert len(logs) == 1
    assert logs[0]["status"] == VendorIntegrationStatus.SKIPPED
    assert logs[0]["action"] == VendorIntegrationAction.RETRY_CREATE


def test_not_found_in_concur_returns_404(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    _patch_logs(monkeypatch, logs)
    monkeypatch.setattr(
        retry_vendor_sync_service,
        "SAPConcurVendorService",
        _concur_returning(None),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            retry_vendor_sync_service.retry_vendor_sync(
                FakeSession(), vendor_code="missing-1"
            )
        )

    assert exc_info.value.status_code == 404
    assert len(logs) == 1
    assert logs[0]["status"] == VendorIntegrationStatus.FAILED
    assert logs[0]["action"] == VendorIntegrationAction.RETRY_CREATE
    assert logs[0]["message"] == "Vendor not found in SAP Concur"


def test_concur_error_returns_502(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    _patch_logs(monkeypatch, logs)
    monkeypatch.setattr(
        retry_vendor_sync_service,
        "SAPConcurVendorService",
        _concur_raising(SAPConcurVendorServiceError("boom")),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            retry_vendor_sync_service.retry_vendor_sync(
                FakeSession(), vendor_code="4029-0"
            )
        )

    assert exc_info.value.status_code == 502
    assert len(logs) == 1
    assert logs[0]["status"] == VendorIntegrationStatus.FAILED
    assert "SAP Concur" in logs[0]["message"]


def test_maconomy_lookup_error_returns_502(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    _patch_logs(monkeypatch, logs)
    monkeypatch.setattr(
        retry_vendor_sync_service,
        "SAPConcurVendorService",
        _concur_returning({"VendorCode": "4029-0"}),
    )
    monkeypatch.setattr(
        retry_vendor_sync_service,
        "MaconomyService",
        _maconomy(lookup_error=MaconomyServiceError("nope")),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            retry_vendor_sync_service.retry_vendor_sync(
                FakeSession(), vendor_code="4029-0"
            )
        )

    assert exc_info.value.status_code == 502
    assert len(logs) == 1
    assert logs[0]["status"] == VendorIntegrationStatus.FAILED


def test_maconomy_create_failure_returns_failed_status(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    _patch_logs(monkeypatch, logs)
    _patch_mapping(monkeypatch, created_mappings=[])
    monkeypatch.setattr(
        retry_vendor_sync_service,
        "SAPConcurVendorService",
        _concur_returning({"VendorCode": "4029-0"}),
    )
    monkeypatch.setattr(
        retry_vendor_sync_service,
        "MaconomyService",
        _maconomy(existing=None, create_error=MaconomyServiceError("rejected")),
    )

    result = asyncio.run(
        retry_vendor_sync_service.retry_vendor_sync(
            FakeSession(), vendor_code="4029-0"
        )
    )

    assert result["status"] == "FAILED"
    assert result["result"]["created"] is False
    assert len(logs) == 1
    assert logs[0]["status"] == VendorIntegrationStatus.FAILED
    assert logs[0]["action"] == VendorIntegrationAction.RETRY_CREATE
    assert logs[0]["message"] == "rejected"


def test_mapping_upsert_updates_existing_row(monkeypatch) -> None:
    logs: list[dict[str, Any]] = []
    created_mappings: list[tuple[str, str]] = []
    existing_mapping = SimpleNamespace(
        id=uuid.uuid4(), maconomy_vendor_code=None
    )
    _patch_logs(monkeypatch, logs)
    _patch_mapping(
        monkeypatch,
        existing_mapping=existing_mapping,
        created_mappings=created_mappings,
    )
    monkeypatch.setattr(
        retry_vendor_sync_service,
        "SAPConcurVendorService",
        _concur_returning({"VendorCode": "4029-0"}),
    )
    monkeypatch.setattr(
        retry_vendor_sync_service,
        "MaconomyService",
        _maconomy(existing=None, created={"vendornumber": "NEW-9"}),
    )
    session = FakeSession()

    result = asyncio.run(
        retry_vendor_sync_service.retry_vendor_sync(
            session, vendor_code="4029-0"
        )
    )

    assert result["status"] == "SUCCESS"
    assert created_mappings == []
    assert existing_mapping.maconomy_vendor_code == "NEW-9"
    assert session.commits == 1
    assert len(logs) == 1
    assert logs[0]["mapping_id"] == existing_mapping.id
    assert logs[0]["maconomy_vendor_code"] == "NEW-9"


def test_blank_vendor_code_returns_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            retry_vendor_sync_service.retry_vendor_sync(
                FakeSession(), vendor_code="   "
            )
        )
    assert exc_info.value.status_code == 400


def test_maconomy_lookup_sends_restricted_filter_payload() -> None:
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
                        "records": [
                            {
                                "data": {
                                    "vendornumber": "O'Brien",
                                    "name1": "Acme",
                                }
                            }
                        ],
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
            return await service.get_vendor_by_code("O'Brien")

    vendor = asyncio.run(run())

    assert captured["path"].endswith("/vendorcard/filter")
    assert captured["json"]["restriction"] == "vendornumber='O''Brien'"
    assert captured["json"]["fields"] == ["name1", "vendornumber"]
    assert captured["json"]["limit"] == 1
    assert captured["json"]["offset"] == 0
    assert vendor == {"vendornumber": "O'Brien", "name1": "Acme"}


def test_maconomy_lookup_returns_none_when_absent() -> None:
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
            return await service.get_vendor_by_code("4029-0")

    assert asyncio.run(run()) is None
