"""Unit tests for the SAP Concur invoice allocation-line mapper.

Covers the 2026-11-18 amendments:
- Quantity -> ``quantity`` (raw float; default ``1`` when missing/blank;
  non-numeric raises ValueError naming Quantity)
- Location (Custom1) -> ``specification4name`` (raw verbatim; default
  ``"-"`` when missing/blank)
- neither new field joins the required check
- sync rule: every data key except the un-sliced Q-1 linkage fields
  must exist in the vendorinvoiceallocation instance slice
- the jobtasks instance payload shape (card jobnumber + taskname table)
"""

import pytest

from app.features.sap_concur_invoice_integration.mappers.maconomy_line_mapper import (
    build_jobtasks_instance_payload,
    build_vendor_invoice_allocation_instance_payload,
    map_concur_invoice_line_to_allocation_row,
)

# Q-1 linkage fields are un-sliced container key fields — written
# without being part of the instance slice (documented exception).
UNSLICED_LINKAGE_FIELDS = {"journalnumber", "journallinenumber"}


def _base_line(**overrides):
    line_item = {
        "LineItemId": "L1",
        "Custom10": "E1",
        "Custom11": "Task-1",
        "Department": "Assurance",
        "UnitPrice": "2",
    }
    line_item.update(overrides)
    return line_item


def _map(**overrides):
    return map_concur_invoice_line_to_allocation_row(
        _base_line(**overrides),
        journalnumber="10585",
        journallinenumber=5,
    )


# ---------------------------------------------------------------------
# Quantity -> quantity
# ---------------------------------------------------------------------
def test_quantity_present_maps_raw_float():
    assert _map(Quantity="3")["data"]["quantity"] == 3.0


def test_quantity_fractional_value_maps_raw_float():
    assert _map(Quantity="2.5")["data"]["quantity"] == 2.5


def test_quantity_missing_defaults_to_one():
    assert _map()["data"]["quantity"] == 1


def test_quantity_blank_defaults_to_one():
    assert _map(Quantity="   ")["data"]["quantity"] == 1


def test_quantity_non_numeric_raises_naming_field():
    with pytest.raises(ValueError, match="Quantity"):
        _map(Quantity="abc")


# ---------------------------------------------------------------------
# Location (Custom1) -> specification4name
# ---------------------------------------------------------------------
def test_location_custom1_maps_raw_value():
    assert _map(Custom1="Tampa")["data"]["specification4name"] == "Tampa"


def test_location_missing_defaults_to_dash():
    assert _map()["data"]["specification4name"] == "-"


def test_location_blank_defaults_to_dash():
    assert _map(Custom1="  ")["data"]["specification4name"] == "-"


# ---------------------------------------------------------------------
# Validation interplay
# ---------------------------------------------------------------------
def test_new_fields_are_optional_not_required():
    payload = _map()

    assert payload["data"]["quantity"] == 1
    assert payload["data"]["specification4name"] == "-"


def test_required_fields_still_enforced_without_new_fields():
    with pytest.raises(ValueError, match="Engagement"):
        map_concur_invoice_line_to_allocation_row(
            _base_line(Custom10=""),
            journalnumber="10585",
            journallinenumber=5,
        )


def test_unparseable_unit_price_still_raises():
    with pytest.raises(ValueError, match="Unit Price"):
        _map(UnitPrice="not-a-number")


# ---------------------------------------------------------------------
# Sync rule: data keys must be covered by the instance slice
# ---------------------------------------------------------------------
def test_data_keys_are_subset_of_instance_table_slice():
    slice_fields = set(
        build_vendor_invoice_allocation_instance_payload()["panes"][
            "table"
        ]["fields"]
    )
    data = _map(Quantity="2", Custom1="Tampa")["data"]

    assert set(data) - UNSLICED_LINKAGE_FIELDS <= slice_fields


def test_data_key_count_is_twelve():
    assert len(_map()["data"]) == 12


def test_quantity_and_specification4name_are_sliced():
    slice_fields = set(
        build_vendor_invoice_allocation_instance_payload()["panes"][
            "table"
        ]["fields"]
    )

    assert {"quantity", "specification4name"} <= slice_fields


# ---------------------------------------------------------------------
# jobtasks instance payload (engagement/task gate prerequisite)
# ---------------------------------------------------------------------
def test_jobtasks_payload_card_contains_jobnumber():
    card_fields = build_jobtasks_instance_payload()["panes"]["card"][
        "fields"
    ]

    assert "jobnumber" in card_fields
    assert "copyfromjobnamevar" in card_fields
    assert "copyfromjobvar" in card_fields


def test_jobtasks_payload_table_contains_taskname_and_description():
    table_fields = build_jobtasks_instance_payload()["panes"]["table"][
        "fields"
    ]

    assert {"taskname", "description"} <= set(table_fields)
