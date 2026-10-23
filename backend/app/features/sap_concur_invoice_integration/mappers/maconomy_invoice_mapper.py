"""Static Maconomy vendor-invoice (card pane) payloads.

Phase 2 of Req[#21]: payloads are static per user direction — the real
SAP Concur -> Maconomy field mapping is a future phase. Values mirror the
user-provided samples exactly.
"""

from typing import Any


def build_vendor_invoice_instance_payload() -> dict[str, Any]:
    """Instance-retrieval payload for the vendorinvoices container.

    Card fields: sliced for the card-create payload. Table fields: sliced
    for the line-row payload — Maconomy only allows writing fields that
    were sliced in at instance retrieval (400 "modify record fields which
    you have sliced out" otherwise), mirroring
    sap_concur_integration's _retrieve_expenses_instance.

    SYNC RULE: if the static line payload's ``data`` keys change, this
    table field list must change with them (slice must always cover every
    key the line payload writes).
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
            # Exactly the 15 keys of map_concur_invoice_line_to_maconomy_line()
            # ["data"] — keep in sync with the line payload (WO[#21.7]).
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
    """Static card-create payload for the vendorinvoices container."""
    return {
        "data": {
            "entrytotalcontrol": 0,
            "transactionnumberseries": "nil",
            "postentryperiod": "nil",
            "companynumber": "",
            "defaulttransactiontype": "",
            "automaticvoucher": True,
        },
        "offset": 0,
        "limit": 100,
    }
