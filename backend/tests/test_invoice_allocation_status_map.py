"""Tests for the allocation_lines_status JSONB builder (user 2026-11-18).

Contract (user-approved plain-string format):
- SUCCESS line -> Maconomy allocation line number (``str | None``)
- FAILED line  -> its ``message`` (any line-level exception: gate
  failures, mapper required/unparseable errors, HTTP/Maconomy errors)
- line items present but ZERO line entries (D-6 skip) ->
  ``{"*": "allocation lines skipped: ..."}``
- no line items -> ``{}``

Keys stay the SAP line id (``LineItemId`` -> ``ID`` -> ``LineNumber``
-> index fallback) via the router's ``_sap_line_id``.
"""

from typing import Any

from app.features.sap_concur_invoice_integration.routers.sap_concur_invoices import (
    _build_allocation_map,
    _sap_line_id,
)

LINE_ID_1 = "D5FC26E64574214DB85F31860CC12CBB"
LINE_ID_2 = "99C0AA12FF6644BB9011223344556677"


def _line_item(line_id: str, **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"LineItemId": line_id}
    item.update(extra)
    return item


def _success(line_index: int, linenumber: str) -> dict[str, Any]:
    return {
        "invoice_id": "INV-1",
        "line_index": line_index,
        "status": "SUCCESS",
        "result": {
            "panes": {
                "table": {
                    "records": [{"data": {"linenumber": linenumber}}]
                }
            }
        },
    }


def _failed(line_index: int, message: str, reason: str | None = None):
    entry: dict[str, Any] = {
        "invoice_id": "INV-1",
        "line_index": line_index,
        "status": "FAILED",
        "message": message,
    }
    if reason:
        entry["reason"] = reason
    return entry


# ---------------------------------------------------------------------
# SUCCESS lines -> Maconomy line number
# ---------------------------------------------------------------------
def test_success_line_stores_maconomy_line_number():
    lines = [_success(0, "5")]
    items = [_line_item(LINE_ID_1)]

    assert _build_allocation_map(lines, items) == {LINE_ID_1: "5"}


def test_success_line_without_extractable_number_stores_none():
    lines = [{"invoice_id": "INV-1", "line_index": 0, "status": "SUCCESS",
              "result": {}}]
    items = [_line_item(LINE_ID_1)]

    assert _build_allocation_map(lines, items) == {LINE_ID_1: None}


# ---------------------------------------------------------------------
# FAILED lines -> plain message string (was null before)
# ---------------------------------------------------------------------
def test_gate_failure_stores_message_not_null():
    message = (
        "Engagement E999 not found in Maconomy - allocation line "
        "creation stopped"
    )
    lines = [_failed(0, message, reason="ENGAGEMENT_NOT_FOUND")]
    items = [_line_item(LINE_ID_1)]

    result = _build_allocation_map(lines, items)

    assert result == {LINE_ID_1: message}


def test_mapper_required_failure_stores_message():
    message = (
        "Missing required Concur invoice line fields for Maconomy "
        "mapping: Engagement, Task"
    )
    lines = [_failed(0, message)]
    items = [_line_item(LINE_ID_1)]

    assert _build_allocation_map(lines, items) == {LINE_ID_1: message}


def test_task_gate_failure_stores_message():
    message = (
        "Task Task-X not found in Maconomy for engagement E1 - "
        "allocation line creation stopped"
    )
    lines = [_failed(1, message, reason="TASK_NOT_FOUND")]
    items = [_line_item(LINE_ID_1), _line_item(LINE_ID_2)]

    assert _build_allocation_map(lines, items) == {LINE_ID_2: message}


def test_http_error_failure_stores_message():
    message = "Maconomy vendorinvoiceallocation request failed"
    lines = [_failed(0, message)]
    items = [_line_item(LINE_ID_1)]

    assert _build_allocation_map(lines, items) == {LINE_ID_1: message}


def test_failure_with_empty_message_gets_fallback_text():
    lines = [_failed(0, "   ")]
    items = [_line_item(LINE_ID_1)]

    assert _build_allocation_map(lines, items) == {
        LINE_ID_1: "allocation line failed"
    }


# ---------------------------------------------------------------------
# Key resolution
# ---------------------------------------------------------------------
def test_key_falls_back_to_line_index_without_line_id():
    lines = [_failed(0, "boom")]
    items = [{}]  # no LineItemId / ID / LineNumber

    assert _build_allocation_map(lines, items) == {"0": "boom"}


def test_key_uses_id_when_line_item_id_absent():
    lines = [_failed(0, "boom")]
    items = [{"ID": "ABC123"}]

    assert _build_allocation_map(lines, items) == {"ABC123": "boom"}


def test_out_of_range_line_index_uses_index_fallback_key():
    lines = [_failed(7, "boom")]
    items = [_line_item(LINE_ID_1)]

    assert _build_allocation_map(lines, items) == {"7": "boom"}


# ---------------------------------------------------------------------
# Mixed batches
# ---------------------------------------------------------------------
def test_mixed_success_and_failure_per_key_values():
    lines = [
        _failed(0, "Missing required Concur invoice line fields for "
                   "Maconomy mapping: Engagement, Task"),
        _success(1, "6"),
    ]
    items = [_line_item(LINE_ID_1), _line_item(LINE_ID_2)]

    assert _build_allocation_map(lines, items) == {
        LINE_ID_1: "Missing required Concur invoice line fields for "
                   "Maconomy mapping: Engagement, Task",
        LINE_ID_2: "6",
    }


# ---------------------------------------------------------------------
# D-6 skip marker / empty cases
# ---------------------------------------------------------------------
def test_d6_skip_with_line_error_stores_star_marker():
    result = _build_allocation_map(
        invoice_lines=[],
        line_items=[_line_item(LINE_ID_1)],
        line_error="journalnumber missing from journal response",
    )

    assert result == {
        "*": "allocation lines skipped: journalnumber missing from "
             "journal response"
    }


def test_d6_skip_without_line_error_still_marks_skip():
    result = _build_allocation_map(
        invoice_lines=[],
        line_items=[_line_item(LINE_ID_1)],
        line_error=None,
    )

    assert result == {"*": "allocation lines skipped"}


def test_no_line_items_stores_empty_dict():
    assert _build_allocation_map(invoice_lines=[], line_items=[]) == {}


def test_no_line_items_with_line_error_still_empty_dict():
    # No line items at all -> nothing to skip (D-2), not a D-6 skip.
    assert _build_allocation_map(
        invoice_lines=[], line_items=[], line_error="whatever"
    ) == {}


# ---------------------------------------------------------------------
# Key helper sanity (shared with the map builder)
# ---------------------------------------------------------------------
def test_sap_line_id_prefers_line_item_id():
    assert _sap_line_id({"LineItemId": "X1", "ID": "X2"}, 3) == "X1"
    assert _sap_line_id({"ID": "X2"}, 3) == "X2"
    assert _sap_line_id({}, 3) == "3"
