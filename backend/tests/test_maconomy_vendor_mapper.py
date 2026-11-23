import pytest

from app.features.sap_concur_vendor_integration.mappers.maconomy_vendor_mapper import (
    DEFAULT_COUNTRY_NAME,
    map_concur_vendor_to_maconomy_vendor_card,
)


def _vendor(**overrides: object) -> dict[str, object]:
    vendor: dict[str, object] = {
        "VendorCode": "4029-0",
        "VendorName": "Acme",
    }
    vendor.update(overrides)
    return vendor


def test_state_matched_case_insensitively_uses_maconomy_name() -> None:
    payload = map_concur_vendor_to_maconomy_vendor_card(
        _vendor(State="tx"),
        {"tx": "TX", "fl": "FL"},
    )
    assert payload["data"]["country"] == "TX"


def test_state_not_in_lookup_falls_back_to_default() -> None:
    payload = map_concur_vendor_to_maconomy_vendor_card(
        _vendor(State="ZZ"),
        {"tx": "TX"},
    )
    assert payload["data"]["country"] == DEFAULT_COUNTRY_NAME


def test_missing_state_falls_back_to_default() -> None:
    payload = map_concur_vendor_to_maconomy_vendor_card(
        _vendor(),
        {"tx": "TX"},
    )
    assert payload["data"]["country"] == DEFAULT_COUNTRY_NAME


def test_blank_state_falls_back_to_default() -> None:
    payload = map_concur_vendor_to_maconomy_vendor_card(
        _vendor(State="   "),
        {"tx": "TX"},
    )
    assert payload["data"]["country"] == DEFAULT_COUNTRY_NAME


def test_fallback_resolves_canonical_casing_from_lookup() -> None:
    payload = map_concur_vendor_to_maconomy_vendor_card(
        _vendor(State="ZZ"),
        {DEFAULT_COUNTRY_NAME: "United_States_Of_America"},
    )
    assert payload["data"]["country"] == "United_States_Of_America"


def test_empty_vendor_code_raises() -> None:
    with pytest.raises(ValueError, match="VendorCode"):
        map_concur_vendor_to_maconomy_vendor_card(_vendor(VendorCode=""), {})


def test_empty_vendor_name_raises() -> None:
    with pytest.raises(ValueError, match="VendorName"):
        map_concur_vendor_to_maconomy_vendor_card(_vendor(VendorName=""), {})
