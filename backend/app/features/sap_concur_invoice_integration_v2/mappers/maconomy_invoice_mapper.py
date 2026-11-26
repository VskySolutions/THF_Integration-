"""Map Concur invoice data to a Maconomy vendor invoice card."""

from datetime import datetime
from math import isfinite
from typing import Any


def _normalize_date(raw: str, source_field: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{source_field} is empty")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    for date_format in ("%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unparseable {source_field}: {value!r}")


def map_concur_invoice_to_maconomy_invoice_card(
    invoice: dict[str, Any],
) -> dict[str, Any]:
    vendor_remittance = invoice.get("VendorRemitAddress")
    if vendor_remittance and not isinstance(vendor_remittance, dict):
        raise ValueError("Invalid Concur VendorRemitAddress")

    vendor_code = str(
        (vendor_remittance or {}).get("VendorCode") or invoice.get("VendorCode") or ""
    ).strip()
    invoice_name = str(invoice.get("Name") or invoice.get("InvoiceName") or "").strip()
    invoice_number = str(invoice.get("InvoiceNumber") or "").strip()
    invoice_date_raw = str(invoice.get("InvoiceDate") or "").strip()
    payment_due_date = str(invoice.get("PaymentDueDate") or "").strip()
    posting_date = str(invoice.get("PostingDate") or "").strip()
    concur_invoice_id = str(
        invoice.get("PaymentRequestId") or invoice.get("ID") or ""
    ).strip()

    missing = [
        name
        for name, value in (
            ("Invoice Name", invoice_name),
            ("InvoiceNumber", invoice_number),
            ("InvoiceDate", invoice_date_raw),
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

    invoice_date = _normalize_date(invoice_date_raw, "InvoiceDate")
    invoice_amount = invoice.get("InvoiceAmount")
    amount_text = "" if invoice_amount is None else str(invoice_amount).strip()
    try:
        amount_currency = float(amount_text) if amount_text else 0
    except ValueError as exc:
        raise ValueError(f"Unparseable InvoiceAmount: {amount_text!r}") from exc
    if not isfinite(amount_currency):
        raise ValueError("InvoiceAmount must be finite")

    data = {
        "vendornumber": vendor_code,
        "invoicedate": invoice_date,
        "invoicenumber": invoice_number,
        "entrytext": invoice_name,
        "currency": "USD",
        # "automaticvoucher": False,
        # "transactionnumber": concur_invoice_id,
        "remark5": concur_invoice_id,
        "amountcurrency": amount_currency,
        "vatcurrency": 0,
        "financevatcode": "",
        "purchaseordernumber": "",
        "documentarchivenumber": "",
        "filename": "",
        "allocationresponsible": "",
        "amountexclvatcurrency": 0,
    }
    if posting_date:
        data["entrydate"] = _normalize_date(posting_date, "PostingDate")
    if payment_due_date:
        data["duedate"] = _normalize_date(payment_due_date, "PaymentDueDate")

    return {"data": data, "offset": 0, "limit": 100}
