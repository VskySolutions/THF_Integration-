"""Static Maconomy vendor-invoice line (table pane) payloads.

Phase 2 of Req[#21]: payloads are static per user direction — the real
SAP Concur line-item -> Maconomy table-row mapping is a future phase.
Values mirror the user-provided samples exactly.
"""

from typing import Any


def build_vendor_invoice_table_init_payload() -> dict[str, Any]:
    """Table-pane init payload — new rows appended at the end."""
    return {"row": "end"}


def map_concur_invoice_line_to_maconomy_line() -> dict[str, Any]:
    """Static table-row payload for one vendor-invoice line."""
    return {
        "data": {
            "vendornumber": "",
            "entrydate": "2026-10-22",
            "invoicedate": "",
            "duedate": "",
            "invoicenumber": "123456789",
            "entrytext": "",
            "currency": "nil",
            "amountcurrency": 0,
            "vatcurrency": 0,
            "financevatcode": "",
            "purchaseordernumber": "",
            "documentarchivenumber": "",
            "filename": "",
            "allocationresponsible": "",
            "amountexclvatcurrency": 0,
        },
        "offset": 0,
        "limit": 100,
        "row": "end",
    }


def build_static_line_item_payloads(count: int = 1) -> list[dict[str, Any]]:
    """Loop-able list of static line payloads (one per Concur line item later)."""
    n = max(int(count), 0)
    return [map_concur_invoice_line_to_maconomy_line() for _ in range(n)]
