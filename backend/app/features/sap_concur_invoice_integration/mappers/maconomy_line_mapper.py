"""Static Maconomy table-init payload for the vendorinvoices container.

Note (WO[#21.9], user correction 2026-10-23): the former static row
builders (`map_concur_invoice_line_to_maconomy_line`,
`build_static_line_item_payloads`) were superseded — those rows were
actually SAP Concur INVOICES, now dynamically built by
``map_concur_invoice_to_maconomy_invoice_row`` in
``maconomy_invoice_mapper.py``. The table pane here therefore holds the
invoices; the real SAP Concur line items (``LineItems.LineItem``) are a
FUTURE phase and will reintroduce line-row builders here.
"""

from typing import Any


def build_vendor_invoice_table_init_payload() -> dict[str, Any]:
    """Table-pane init payload — new rows appended at the end."""
    return {"row": "end"}
