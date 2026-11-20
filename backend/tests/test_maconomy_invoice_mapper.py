"""Unit tests for the SAP Concur invoice -> Maconomy invoice-row mapper.

Covers the 2026-11-17 date-mapping amendment:
- ``PaymentDueDate`` -> ``duedate`` (key omitted when missing/empty)
- ``PostingDate`` -> ``entrydate`` ("" when missing/empty)
- ``InvoiceDate`` -> ``invoicedate`` only (still required)
"""

import pytest

from app.features.sap_concur_invoice_integration.mappers.maconomy_invoice_mapper import (
    build_vendor_invoice_instance_payload,
    map_concur_invoice_to_maconomy_invoice_row,
)


def _base_invoice(**overrides):
    invoice = {
        "Name": "ACME Consulting Invoice",
        "InvoiceNumber": "INV-1001",
        "InvoiceDate": "2026-11-01",
        "PaymentRequestId": "PR-9001",
        "VendorRemitAddress": {"VendorCode": "V-77"},
    }
    invoice.update(overrides)
    return invoice


def test_all_dates_present_maps_each_source_field():
    payload = map_concur_invoice_to_maconomy_invoice_row(
        _base_invoice(
            PaymentDueDate="2026-12-15",
            PostingDate="2026-11-10",
        )
    )
    data = payload["data"]

    assert data["duedate"] == "2026-12-15"
    assert data["entrydate"] == "2026-11-10"
    assert data["invoicedate"] == "2026-11-01"
    assert payload["offset"] == 0
    assert payload["limit"] == 100
    assert payload["row"] == "end"


def test_entrydate_uses_posting_date_not_invoice_date():
    data = map_concur_invoice_to_maconomy_invoice_row(
        _base_invoice(PostingDate="2026-11-10")
    )["data"]

    assert data["entrydate"] == "2026-11-10"
    assert data["invoicedate"] == "2026-11-01"


def test_missing_payment_due_date_omits_duedate_key():
    data = map_concur_invoice_to_maconomy_invoice_row(_base_invoice())["data"]

    assert "duedate" not in data


def test_empty_payment_due_date_omits_duedate_key():
    data = map_concur_invoice_to_maconomy_invoice_row(
        _base_invoice(PaymentDueDate="   ")
    )["data"]

    assert "duedate" not in data


def test_missing_posting_date_writes_empty_entrydate():
    data = map_concur_invoice_to_maconomy_invoice_row(_base_invoice())["data"]

    assert data["entrydate"] == ""
    assert data["invoicedate"] == "2026-11-01"


def test_empty_posting_date_writes_empty_entrydate():
    data = map_concur_invoice_to_maconomy_invoice_row(
        _base_invoice(PostingDate="")
    )["data"]

    assert data["entrydate"] == ""


def test_alternate_date_formats_normalize():
    data = map_concur_invoice_to_maconomy_invoice_row(
        _base_invoice(
            InvoiceDate="11/01/2026",
            PostingDate="11/10/2026",
            PaymentDueDate="12/15/2026",
        )
    )["data"]

    assert data["invoicedate"] == "2026-11-01"
    assert data["entrydate"] == "2026-11-10"
    assert data["duedate"] == "2026-12-15"


def test_unparseable_posting_date_raises_naming_field():
    with pytest.raises(ValueError, match="PostingDate"):
        map_concur_invoice_to_maconomy_invoice_row(
            _base_invoice(PostingDate="not-a-date")
        )


def test_unparseable_payment_due_date_raises_naming_field():
    with pytest.raises(ValueError, match="PaymentDueDate"):
        map_concur_invoice_to_maconomy_invoice_row(
            _base_invoice(PaymentDueDate="not-a-date")
        )


def test_missing_invoice_date_still_raises():
    with pytest.raises(ValueError, match="InvoiceDate"):
        map_concur_invoice_to_maconomy_invoice_row(
            _base_invoice(InvoiceDate="")
        )


def test_missing_invoice_name_raises():
    with pytest.raises(ValueError, match="Invoice Name"):
        map_concur_invoice_to_maconomy_invoice_row(_base_invoice(Name=""))


def test_optional_dates_are_not_required():
    payload = map_concur_invoice_to_maconomy_invoice_row(
        _base_invoice(PostingDate="", PaymentDueDate="")
    )

    assert payload["data"]["entrydate"] == ""
    assert "duedate" not in payload["data"]


def test_data_keys_are_subset_of_instance_table_slice():
    slice_fields = set(
        build_vendor_invoice_instance_payload()["panes"]["table"]["fields"]
    )
    with_due = map_concur_invoice_to_maconomy_invoice_row(
        _base_invoice(PaymentDueDate="2026-12-15", PostingDate="2026-11-10")
    )["data"]
    without_due = map_concur_invoice_to_maconomy_invoice_row(_base_invoice())["data"]

    assert set(with_due) <= slice_fields
    assert set(without_due) <= slice_fields
    assert len(with_due) == 16
    assert len(without_due) == 15
