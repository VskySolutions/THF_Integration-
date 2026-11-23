import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.features.sap_concur_vendor_integration.services import (
    maconomy_services,
)
from app.features.sap_concur_vendor_integration.services.maconomy_services import (
    MaconomyService,
    MaconomyServiceError,
)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        maconomy_url="http://maconomy.test",
        maconomy_shortname="shortname",
        maconomy_username="user",
        maconomy_password=SimpleNamespace(get_secret_value=lambda: "pw"),
    )


def _login_ok(request: httpx.Request) -> httpx.Response | None:
    if request.url.path.endswith("/login"):
        return httpx.Response(
            204, headers={"Maconomy-Reconnect": "token-1"}
        )
    return None


def _countries_response(*names: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "panes": {
                "filter": {
                    "records": [{"data": {"name": name}} for name in names]
                }
            }
        },
    )


def test_get_country_names_posts_countries_filter_and_builds_lookup() -> None:
    captured: dict[str, Any] = {}

    def handle_request(request: httpx.Request) -> httpx.Response:
        login = _login_ok(request)
        if login is not None:
            return login
        captured["path"] = request.url.path
        captured["json"] = json.loads(request.content)
        return _countries_response("TX", "Florida", "")

    async def run() -> dict[str, str]:
        async with httpx.AsyncClient(
            base_url="http://maconomy.test",
            transport=httpx.MockTransport(handle_request),
        ) as client:
            service = MaconomyService(client, settings=_settings())
            return await service.get_country_names()

    lookup = asyncio.run(run())

    assert captured["path"].endswith("/countries/filter")
    assert captured["json"] == {
        "fields": [
            "countrycode",
            "countrynumber",
            "eucountrycode",
            "isocode",
            "name",
        ],
        "limit": 500,
    }
    assert lookup == {"tx": "TX", "florida": "Florida"}


def test_get_country_names_cached_per_instance() -> None:
    calls = {"count": 0}

    def handle_request(request: httpx.Request) -> httpx.Response:
        login = _login_ok(request)
        if login is not None:
            return login
        calls["count"] += 1
        return _countries_response("TX")

    async def run() -> tuple[dict[str, str], dict[str, str]]:
        async with httpx.AsyncClient(
            base_url="http://maconomy.test",
            transport=httpx.MockTransport(handle_request),
        ) as client:
            service = MaconomyService(client, settings=_settings())
            first = await service.get_country_names()
            second = await service.get_country_names()
            return first, second

    first, second = asyncio.run(run())

    assert calls["count"] == 1
    assert first is second
    assert first == {"tx": "TX"}


def test_get_country_names_http_error_raises() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        login = _login_ok(request)
        if login is not None:
            return login
        return httpx.Response(500)

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://maconomy.test",
            transport=httpx.MockTransport(handle_request),
        ) as client:
            service = MaconomyService(client, settings=_settings())
            await service.get_country_names()

    with pytest.raises(
        MaconomyServiceError, match="country list request failed"
    ):
        asyncio.run(run())


def test_get_country_names_invalid_shape_raises() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        login = _login_ok(request)
        if login is not None:
            return login
        return httpx.Response(200, json={"panes": {}})

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://maconomy.test",
            transport=httpx.MockTransport(handle_request),
        ) as client:
            service = MaconomyService(client, settings=_settings())
            await service.get_country_names()

    with pytest.raises(
        MaconomyServiceError, match="Invalid Maconomy countries filter"
    ):
        asyncio.run(run())


def test_get_country_names_no_usable_values_raises() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        login = _login_ok(request)
        if login is not None:
            return login
        return _countries_response("", "   ")

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://maconomy.test",
            transport=httpx.MockTransport(handle_request),
        ) as client:
            service = MaconomyService(client, settings=_settings())
            await service.get_country_names()

    with pytest.raises(
        MaconomyServiceError, match="no usable values"
    ):
        asyncio.run(run())


def test_create_vendor_fetches_countries_before_instance_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    original_mapper = (
        maconomy_services.map_concur_vendor_to_maconomy_vendor_card
    )

    def spy_mapper(
        sap_vendor: dict[str, Any], country_names: dict[str, str]
    ) -> dict[str, Any]:
        captured["country_names"] = country_names
        return original_mapper(sap_vendor, country_names)

    monkeypatch.setattr(
        maconomy_services,
        "map_concur_vendor_to_maconomy_vendor_card",
        spy_mapper,
    )

    def handle_request(request: httpx.Request) -> httpx.Response:
        login = _login_ok(request)
        if login is not None:
            return login
        if request.url.path.endswith("/countries/filter"):
            return _countries_response("TX")
        if request.url.path.endswith("/vendorcard/instances"):
            return httpx.Response(500)
        raise AssertionError(f"unexpected call: {request.url.path}")

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://maconomy.test",
            transport=httpx.MockTransport(handle_request),
        ) as client:
            service = MaconomyService(client, settings=_settings())
            await service.create_vendor(
                {"VendorCode": "4029-0", "VendorName": "Acme", "State": "tx"}
            )

    with pytest.raises(
        MaconomyServiceError, match="vendor creation request failed"
    ):
        asyncio.run(run())

    assert captured["country_names"] == {"tx": "TX"}


def test_create_vendor_fails_when_country_list_unavailable() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        login = _login_ok(request)
        if login is not None:
            return login
        if request.url.path.endswith("/countries/filter"):
            return httpx.Response(503)
        raise AssertionError(f"unexpected call: {request.url.path}")

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://maconomy.test",
            transport=httpx.MockTransport(handle_request),
        ) as client:
            service = MaconomyService(client, settings=_settings())
            await service.create_vendor(
                {"VendorCode": "4029-0", "VendorName": "Acme"}
            )

    with pytest.raises(
        MaconomyServiceError, match="country list request failed"
    ):
        asyncio.run(run())
