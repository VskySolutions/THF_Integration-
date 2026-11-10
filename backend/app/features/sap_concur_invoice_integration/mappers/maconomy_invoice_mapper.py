"""Maconomy vendor-invoice payloads (journal card + invoice rows).

- Card pane payload: STATIC — creates the JOURNAL (Req[#21] Phase 2/3;
  2026-11-09 amendments: `defaulttransactiontype` = "Vendor Invoice",
  `automaticvoucher` EXCLUDED — Auto. Trans. No. Box not written, no
  currency field on the card).
- Table pane payload: one dynamically mapped invoice row per SAP Concur
  invoice (Req[#27] FR-3): Invoice Name -> `entrytext`, Invoice Number ->
  `invoicenumber`, Invoice Date -> `entrydate` + `invoicedate`
  (YYYY-MM-DD), SAP Concur invoice id (`PaymentRequestId`/`ID`) ->
  `remarks5` (user 2026-11-09), SAP vendor code
  (`VendorRemitAddress.VendorCode`, root `VendorCode` fallback) ->
  `vendornumber` (DYNAMIC — user 2026-11-10, replaces the former
  static sample vendor number), `currency` static "USD" (invoice row
  only — supersedes the dynamic CurrencyCode mapping).
"""

from datetime import datetime
from typing import Any


def build_vendor_invoice_instance_payload() -> dict[str, Any]:
    """Instance-retrieval payload for the vendorinvoices container.

    Card fields: sliced for the STATIC journal card payload (17 fields —
    the card pane creates a journal, no Concur mapping). Table fields:
    sliced for the invoice-row payload — must cover EVERY key of
    ``map_concur_invoice_to_maconomy_invoice_row(...)["data"]`` (16 keys
    incl. the dynamic entrydate/invoicedate/invoicenumber/entrytext +
    remarks5 + static currency "USD"). Maconomy only allows writing
    fields that were sliced in at instance retrieval (400 "modify record
    fields which you have sliced out" otherwise), mirroring
    sap_concur_integration's _retrieve_expenses_instance.

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
                    "remark5",
                ]
            },
        }
    }


def map_concur_invoice_to_maconomy_vendor_invoice() -> dict[str, Any]:
    """Card-create payload — the card pane creates a JOURNAL.

    Always the static payload (user correction 2026-10-23: "card is a
    journal it will always use the static payload" — no Concur mapping
    happens on the card; Concur invoices go into the table via
    ``map_concur_invoice_to_maconomy_invoice_row``).

    Req[#27] FR-4 amendments (user 2026-11-09):
    - ``defaulttransactiontype`` = "Vendor Invoice" (was "")
    - ``automaticvoucher`` REMOVED — Auto. Trans. No. Box is excluded;
      Maconomy's default applies (the field stays in the instance slice
      as read-only — slicing != writing)
    - no currency field on the card (USD applies to the invoice ROW only)
    """
    return {
        "data": {
            "entrytotalcontrol": 0,
            "transactionnumberseries": "nil",
            "postentryperiod": "nil",
            "companynumber": "100",
            "defaulttransactiontype": "Vendor Invoice",
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
    """Invoice-row (table pane) payload — dynamic Concur→Maconomy mapping.

    Req[#27] FR-3 (live-confirmed keys, WO[#27.1] Step 1, 2026-11-09):
    - ``Name`` (Invoice Name) → ``entrytext``
    - ``InvoiceNumber`` → ``invoicenumber``
    - ``InvoiceDate`` → ``entrydate`` AND ``invoicedate`` (YYYY-MM-DD)
    - ``PaymentRequestId``/``ID`` (SAP Concur invoice id) → ``remarks5``
      (user 2026-11-09: "remarks5 field in maconomy vendorinvoices will
      store the sap concur invoice id")
    - ``VendorRemitAddress.VendorCode`` (root ``VendorCode`` fallback)
      → ``vendornumber`` (DYNAMIC — user 2026-11-10: "SAP vendorcode
      should map to the vendornumber"; replaces the former static
      sample vendor number; invoice rows only, not the allocation
      line)
    - ``currency`` = static "USD" — INVOICE ROW ONLY, the journal card
      writes no currency field (user 2026-11-09; supersedes the dynamic
      CurrencyCode mapping)

    Missing/empty Invoice Name / InvoiceNumber / InvoiceDate /
    invoice id / SAP vendor code raises ``ValueError`` naming the
    field(s) (service records a per-invoice FAILED entry and continues
    the batch — required set is now 5). ``CurrencyCode`` is no longer
    required (currency is static). Every ``data`` key must be present
    in the instance table slice (16/16 — sync rule; `vendornumber` was
    already sliced — only its VALUE source changed).
    """
    invoice_name = str(invoice.get("Name") or invoice.get("InvoiceName") or "").strip()
    invoice_number = str(invoice.get("InvoiceNumber") or "").strip()
    entry_date = str(invoice.get("InvoiceDate") or "").strip()
    concur_invoice_id = str(
        invoice.get("PaymentRequestId") or invoice.get("ID") or ""
    ).strip()
    vendor_remittance = invoice.get("VendorRemitAddress") or {}
    vendor_code = str(
        vendor_remittance.get("VendorCode")
        or invoice.get("VendorCode")
        or ""
    ).strip()

    missing = [
        name
        for name, value in (
            ("Invoice Name", invoice_name),
            ("InvoiceNumber", invoice_number),
            ("InvoiceDate", entry_date),
            ("PaymentRequestId/ID", concur_invoice_id),
            ("VendorRemitAddress.VendorCode", vendor_code),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Missing required Concur invoice fields for Maconomy "
            f"mapping: {', '.join(missing)}"
        )

    normalized_date = _normalize_entry_date(entry_date)

    return {
        "data": {
            "vendornumber": vendor_code,       # dynamic: SAP vendor code (user 2026-11-10)
            "entrydate": normalized_date,       # dynamic: InvoiceDate → YYYY-MM-DD
            "invoicedate": normalized_date,     # dynamic: InvoiceDate → YYYY-MM-DD
            "duedate": "",
            "invoicenumber": invoice_number,    # dynamic: InvoiceNumber
            "entrytext": invoice_name,          # dynamic: Invoice Name (Description)
            "currency": "USD",                  # static (user 2026-11-09 — invoice row only)
            "remark5": concur_invoice_id,      # dynamic: SAP Concur invoice id (user 2026-11-09)
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
