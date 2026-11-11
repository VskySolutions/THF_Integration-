"""Maconomy line payloads for the vendorinvoiceallocation container (Req[#27]).

Contents:
- ``build_vendor_invoice_table_init_payload()`` — table-pane init
  (``{"row": "end"}``), reused by BOTH containers' table init.
- ``build_vendor_invoice_allocation_instance_payload()`` — instance
  retrieval for ``vendorinvoiceallocation`` (stakeholder 62-field slice
  from WO[#21.11] + ``linenumber`` (WO[#27.12]) = **63 table fields**;
  R-9 resolved 2026-11-10: Maconomy REJECTED the added ``unitprice``
  field name with 400 "Invalid field name 'unitprice'
  ... for the 'table' pane"; the container's valid unit-price field is
  ``unitpricecurrency``, user-confirmed; empty card slice — no card
  writes for allocation lines).
- ``map_concur_invoice_line_to_allocation_row()`` — dynamic per-line
  payload (**10 data keys** + envelope), mapping (Req[#27] FR-7):
  **Custom10 → ``jobnumber``, Custom11 → ``taskname``** (user
  2026-11-10 — custom slot is the PRIMARY source, named key fallback
  only), Unit Price → ``unitpricecurrency`` (user 2026-11-10 confirms
  the Maconomy field name; raw float value — NOT amountcurrency, NOT
  the expense mapper's ×100), Department → ``entityname``, plus the
  **Q-1 linkage pair** ``journalnumber`` (str, phase-3 journal) +
  ``journallinenumber`` (int, the invoice ROW's line number) — user
  2026-11-10: both are REQUIRED for the line to land in the respective
  journal/invoice row.

Concur key resolution (WO[#27.1] Step 1, live-confirmed 2026-11-09;
slot order user-locked 2026-11-10 / WO[#27.5]): invoice LINES carry no
fields literally named Engagement/Task/Department; values live in the
line's custom slots (same convention as expenses: custom10 =
Engagement, custom11 = Task, custom2 = Department — Req[#26]/Req[#8]).
Resolution order per field: **the custom slot FIRST, then the named
key** (user 2026-11-10: "custom10 | jobnumber, custom11 | Task").
Unit Price is the live-confirmed ``UnitPrice``.
NOTE: on current test data ``Custom10``/``Custom11`` are null → those
lines fail required-field validation until Concur data is populated
(data-readiness, mirrors Req[#26] R-3). Confirm slot assignment with the
user if values differ.

Historical note (WO[#21.9]): the former static row builders
(`map_concur_invoice_line_to_maconomy_line`, `build_static_line_item_payloads`)
were superseded — those rows were SAP Concur INVOICES, now built by
``map_concur_invoice_to_maconomy_invoice_row`` in ``maconomy_invoice_mapper.py``.
"""

from typing import Any


def build_vendor_invoice_table_init_payload() -> dict[str, Any]:
    """Table-pane init payload — new rows appended at the end."""
    return {"row": "end"}


def build_vendor_invoice_allocation_instance_payload() -> dict[str, Any]:
    """Instance-retrieval payload for the vendorinvoiceallocation container.

    Card fields: empty (no card writes for allocation lines). Table
    fields: stakeholder 62-field slice (WO[#21.11]) verbatim +
    ``linenumber`` = **63 fields** (WO[#27.12] — allocation-line
    numbers must be returned on record projections; the Q-1 linkage
    fields ``journalnumber``/``journallinenumber`` are un-sliced
    container key fields — written/returned without slicing).
    R-9 resolved 2026-11-10 (user-confirmed): the
    container has NO ``unitprice`` field (live 400), only
    ``unitpricecurrency`` which is already in the slice. SYNC RULE:
    every key of
    ``map_concur_invoice_line_to_allocation_row(...)["data"]`` must be
    present in this slice (Maconomy rejects writes to unsliced fields).
    """

    return {

    "panes": {
        "card": {
            "fields": [
                "allocatedexclvatcurrencyvar",
                "allocatedinclvatcurrencyvar",
                "allocatedvat1currencyvar",
                "allocatedvat2currencyvar",
                "allocatedvat3currencyvar",
                "allocatedvatcurrencyvar",
                "allocationcodename",
                "allocationresponsible",
                "allocationresponsiblenamevar",
                "amountcurrency",
                "amountexcldiscountcurrencyvar",
                "amountexclvatcurrency",
                "approvalgroupdatesubmittedvar",
                "approvalgroupinstancekey",
                "approvalgroupsubmittedbyvar",
                "approvalhierarchyenabledheadervar",
                "approvalhierarchyenabledlinesvar",
                "area",
                "bankaccount",
                "bankregistrationnumber",
                "basecurrencyvar",
                "cardprojectdescriptionvar",
                "cardrelationtitlevar",
                "cashdiscountdate",
                "companynumber",
                "companyvatcode",
                "copyfrominvoicenumber",
                "copyfromjournallinenumber",
                "copyfromjournalnumber",
                "copyfromvendornumber",
                "creditmemoreference",
                "currency",
                "disclosable",
                "documentarchivenumber",
                "documentdescriptionvar",
                "duedate",
                "entityname",
                "entrydate",
                "entrytext",
                "exchangerate",
                "filename",
                "financevatcode",
                "financevatcode2",
                "financevatcode3",
                "fixedexchangerateforpayment",
                "headerapprovaldatevar",
                "headerapprovedorrejectedbyvar",
                "headercurrentapprovalstatusdescriptionvar",
                "headerremarkvar",
                "invoicecompanynamevar",
                "invoicedate",
                "invoicenumber",
                "journalnumber",
                "locationname",
                "nextheaderapproverdescriptionvar",
                "nextheaderapproveremployeenumbervar",
                "nextheaderapprovernamevar",
                "nonallocatedexvatcurrency",
                "nonallocatedinclvatcurrencyvar",
                "nonallocatedvat1currencyvar",
                "nonallocatedvat2currencyvar",
                "nonallocatedvat3currencyvar",
                "nonallocatedvatcurrency",
                "numberoflinesmissingapprovalvar",
                "numberofrejectedlinesvar",
                "originalexchangeratewhencopying",
                "payeridentification",
                "paymentbankaccountvar",
                "paymentbankregistrationnumbervar",
                "paymentdescription",
                "paymentmode",
                "paymentvendornumber",
                "paywhenpaid",
                "possiblecashdiscountcurrency",
                "possiblecashdiscountpercentage",
                "posted",
                "projectname",
                "purchaseordernumber",
                "purchasetransactiontype",
                "reallocationdate",
                "referencedate",
                "registrationcodename",
                "remark1",
                "remark2",
                "remark3",
                "reopened",
                "responsible",
                "responsiblenamevar",
                "reversewhencopying",
                "showpostedentriesvar",
                "showreversedentriesvar",
                "standardtext",
                "status",
                "subledgerentrytype",
                "submitted",
                "tablerelationtitlevar",
                "transactionnumber",
                "transactiontype",
                "vat1currency",
                "vat2currency",
                "vat3currency",
                "vatcurrency",
                "vendorgiro",
                "vendorinvoicecreationvar",
                "vendorinvoicestatusvar",
                "vendorname1var",
                "vendornumber",
                "workflowstatusvar"
            ]
        },
        "table": {
            "fields": [
                "accountnumber",
                "amountcurrency",
                "amountinclvatcurrency",
                "employeenamevar",
                "employeenumber",
                "entityname",
                "entrytext",
                "financevatcode",
                "financevatcode2",
                "financevatcode3",
                "itemnumber",
                "jobnamevar",
                "jobnumber",
                "lineaccounttextvar",
                "lineapprovaldatevar",
                "lineapprovedorrejectedbyvar",
                "linecurrentstatusvar",
                "linelocalaccountdescriptionvar",
                "linenumber",
                "lineremarkvar",
                "localaccountnumber",
                "localspec10name",
                "localspec1name",
                "localspec2name",
                "localspec3name",
                "localspec4name",
                "localspec5name",
                "localspec6name",
                "localspec7name",
                "localspec8name",
                "localspec9name",
                "locationname",
                "movementtransactionlinenumber",
                "movementtransactionnumber",
                "nextlineapproverdescriptionvar",
                "nextlineapproveremployeenumbervar",
                "nextlineapprovernamevar",
                "numberof",
                "posted",
                "projectname",
                "purchaselinetype",
                "purposename",
                "reversed",
                "specification10name",
                "specification1name",
                "specification2name",
                "specification3name",
                "specification4name",
                "specification5name",
                "specification6name",
                "specification7name",
                "specification8name",
                "specification9name",
                "supplierdeliverynotenumber",
                "taskname",
                "tasktextvar",
                "totalforsubcontractorreconciliation",
                "unit",
                "unitpricecurrency",
                "vat1currency",
                "vat2currency",
                "vat3currency",
                "instancekey"
            ]
        }
    }
}
 


def _concur_line_value(line_item: dict[str, Any], *keys: str) -> str:
    """First non-empty value among ``keys`` (named key first, then slot)."""
    for key in keys:
        value = str(line_item.get(key) or "").strip()
        if value:
            return value
    return ""


def map_concur_invoice_line_to_allocation_row(
    line_item: dict[str, Any],
    journalnumber: Any,
    journallinenumber: Any,
) -> dict[str, Any]:
    """Concur invoice line → Maconomy allocation row (Req[#27] FR-7).

    **10 ``data`` keys** (user payload — ``unitpricecurrency`` per user
    confirmation 2026-11-10, R-9 resolved; + the 2 Q-1 linkage fields)
    + envelope ``offset 0 / limit 100 / row "end"``. Mapping:

    - ``jobnumber``        ← Custom10     (PRIMARY, user 2026-11-10;
      ``Engagement`` kept as fallback only)
    - ``taskname``         ← Custom11     (PRIMARY, user 2026-11-10;
      ``Task`` kept as fallback only)
    - ``unitpricecurrency`` ← Unit Price  (live-confirmed ``UnitPrice``,
      raw float — NOT the expense mapper's ×100 convention)
    - ``entityname``       ← Department   (``Department`` → ``Custom2``)
    - ``journalnumber``    ← ``journalnumber`` arg (str — the journal
      created in phase 3; user example ``"10585"``)
    - ``journallinenumber`` ← ``journallinenumber`` arg (int — the
      invoice ROW's line number in that journal; user example ``5``)
    - ``accountnumber`` / ``entrytext`` / ``financevatcode`` /
      ``locationname`` → static ``""`` defaults

    Q-1 linkage (user 2026-11-10): "In order to create the allocation
    line in respective journal and invoice line we need to add them in
    the payload" — both linkage values are REQUIRED.

    Missing/empty mapped field raises ``ValueError`` naming the field(s)
    (service records the line FAILED and continues the batch); a
    non-numeric Unit Price or ``journallinenumber`` also raises
    ``ValueError``. Every ``data`` key is covered by the 63-field
    instance slice (10 ⊆ 63).
    """
    engagement = _concur_line_value(line_item, "Custom10", "Engagement")
    task = _concur_line_value(line_item, "Custom11", "Task")
    department = _concur_line_value(line_item, "Department", "Custom2")
    unit_price_raw = _concur_line_value(line_item, "UnitPrice", "Unit Price")
    journal_number_value = str(journalnumber or "").strip()
    journal_line_value = (
        "" if journallinenumber is None else str(journallinenumber).strip()
    )

    missing = [
        name
        for name, value in (
            ("Engagement", engagement),
            ("Task", task),
            ("UnitPrice", unit_price_raw),
            ("Department", department),
            ("journalnumber", journal_number_value),
            ("journallinenumber", journal_line_value),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Missing required Concur invoice line fields for Maconomy "
            f"mapping: {', '.join(missing)}"
        )

    try:
        unit_price: float = float(unit_price_raw)
    except ValueError as exc:
        raise ValueError(
            f"Unparseable Unit Price for unitpricecurrency: "
            f"{unit_price_raw!r}"
        ) from exc

    try:
        journal_line_number: int = int(journal_line_value)
    except ValueError as exc:
        raise ValueError(
            f"Unparseable journallinenumber for allocation linkage: "
            f"{journallinenumber!r}"
        ) from exc

    return {
        "data": {
            "accountnumber": "",
            "jobnumber": engagement,
            "journalnumber": journal_number_value,
            "journallinenumber": journal_line_number,
            "taskname": task,
            "entrytext": "",
            "unitpricecurrency": unit_price,
            "financevatcode": "",
            "locationname": "",
            "entityname": department,
        },
        "offset": 0,
        "limit": 100,
        "row": "end",
    }
