"""Static Maconomy vendor-invoice (card pane) payloads.

Phase 2 of Req[#21]: payloads are static per user direction — the real
SAP Concur -> Maconomy field mapping is a future phase. Values mirror the
user-provided samples exactly.
"""

from datetime import datetime
from typing import Any


def build_vendor_invoice_instance_payload() -> dict[str, Any]:
    """Instance-retrieval payload for the vendorinvoices container.

    Card fields: sliced for the STATIC journal card payload (17 fields —
    the card pane creates a journal, no Concur mapping). Table fields:
    sliced for the invoice-row payload — must cover EVERY key of
    ``map_concur_invoice_to_maconomy_invoice_row(...)["data"]`` (16 keys
    incl. the dynamic basecurrency/invoicenumber/entrydate). Maconomy
    only allows writing fields that were sliced in at instance retrieval
    (400 "modify record fields which you have sliced out" otherwise),
    mirroring sap_concur_integration's _retrieve_expenses_instance.

    SYNC RULES: if the static card payload's ``data`` keys change, update
    ``panes.card.fields``; if the invoice-row payload's ``data`` keys
    change, update ``panes.table.fields`` (slice must always cover every
    key the payload writes).
    """
    return {
        "panes": {
            "card": {
                "fields": [
                    "automaticvoucher",
                    "basecurrency",
                    "companyname1var",
                    "companynumber",
                    "createddate",
                    "defaulttransactiontype",
                    "entrytotalcontrol",
                    "entrytotalcurrent",
                    "entrytotaldifference",
                    "journalnumber",
                    "layoutnamevar",
                    "nameofuser",
                    "period",
                    "periodend",
                    "periodnumber",
                    "postentryperiod",
                    "transactionnumberseries",
                ]
            },
            "table": {
                "fields": [
                    "vendornumber",
                    "entrydate",
                    "invoicedate",
                    "duedate",
                    "invoicenumber",
                    "entrytext",
                    "currency",
                    "amountcurrency",
                    "vatcurrency",
                    "financevatcode",
                    "purchaseordernumber",
                    "documentarchivenumber",
                    "filename",
                    "allocationresponsible",
                    "amountexclvatcurrency",
                ]
            },
        }
    }


def map_concur_invoice_to_maconomy_vendor_invoice() -> dict[str, Any]:
    """Card-create payload — the card pane creates a JOURNAL.

    Always the static Phase 2 payload (user correction 2026-10-23:
    "card is a journal it will always use the static payload" — no
    Concur mapping happens on the card; Concur invoices go into the
    table via ``map_concur_invoice_to_maconomy_invoice_row``).
    """
    return {
        "data": {
            "entrytotalcontrol": 0,
            "transactionnumberseries": "nil",
            "postentryperiod": "nil",
            "companynumber": "100",
            "defaulttransactiontype": "",
            "automaticvoucher": True,
        },
        "offset": 0,
        "limit": 100,
    }


def _normalize_entry_date(raw: str) -> str:
    """Concur InvoiceDate -> Maconomy YYYY-MM-DD (raises ValueError w/ raw)."""
    value = str(raw or "").strip()
    if not value:
        raise ValueError("InvoiceDate is empty")
    try:                                   # ISO, ISO-time, space, Z (py3.11)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    for fmt in ("%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unparseable InvoiceDate for entrydate: {value!r}")


def map_concur_invoice_to_maconomy_invoice_row(
    invoice: dict[str, Any],
) -> dict[str, Any]:
    """Invoice-row (table pane) payload — dynamic Concur→Maconomy mapping (FR-12).

    Mapped: ``CurrencyCode``→``basecurrency``,
    ``InvoiceNumber``→``invoicenumber``, ``InvoiceDate``→``entrydate``.
    Remaining fields static (user's original invoice-row sample).
    Missing/empty mapped field raises ``ValueError`` naming the field(s)
    (service records a per-invoice FAILED entry and continues the batch).
    """
    currency_code = str(invoice.get("CurrencyCode") or "").strip()
    invoice_number = str(invoice.get("InvoiceNumber") or "").strip()
    entry_date = str(invoice.get("InvoiceDate") or "").strip()

    missing = [
        name
        for name, value in (
            ("CurrencyCode", currency_code),
            ("InvoiceNumber", invoice_number),
            ("InvoiceDate", entry_date),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Missing required Concur invoice fields for Maconomy "
            f"mapping: {', '.join(missing)}"
        )

    return {
        "data": {
            "vendornumber": "1003-0",          # static (sample)
            "entrydate": _normalize_entry_date(entry_date),   # dynamic: InvoiceDate → YYYY-MM-DD
            "invoicedate": "",
            "duedate": "",
            "invoicenumber": invoice_number,    # dynamic: InvoiceNumber
            "entrytext": "",
            "currency": currency_code,      # dynamic: CurrencyCode
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
