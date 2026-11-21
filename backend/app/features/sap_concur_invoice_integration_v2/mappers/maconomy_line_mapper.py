"""Instance fields and allocation row mapping for the invoice's shared instance."""

from decimal import Decimal, DecimalException
from typing import Any

def build_vendor_invoice_table_init_payload() -> dict[str, Any]:
    return {"row": "end"}


def build_jobtasks_instance_payload() -> dict[str, Any]:
    """Request the task fields used when looking up an engagement."""
    return {
        "panes": {
            "card": {
                "fields": [
                    "copyfromjobnamevar",
                    "copyfromjobvar",
                    "jobnumber",
                ],
            },
            "table": {
                "fields": [
                    "activitynumber",
                    "activitytextvar",
                    "activitytypecosttypevar",
                    "allowexpenseregistration",
                    "allowinvoicingonaccount",
                    "allowmileageregistration",
                    "allowpurchasing",
                    "allowtimeregistration",
                    "approvaldate",
                    "approved",
                    "blocked",
                    "description",
                    "jobpricegroupnumber",
                    "linenumber",
                    "overwriteactivity",
                    "overwriteproject",
                    "projectname",
                    "purposename",
                    "riskfund",
                    "taskgroupinfochanged",
                    "tasklist",
                    "taskname",
                    "usedailydescriptions",
                    "instancekey",
                ],
            },
        },
    }


def build_vendor_invoice_allocation_instance_payload() -> dict[str, Any]:
    """Request the fields for the shared invoice card and allocation table."""
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
                    "remark5",
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
                    "workflowstatusvar",
                ],
            },
            "table": {
                "fields": [
                    "accountactivitytext",
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
                    "instancekey",
                ],
            },
        },
    }


def line_value(line_item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(line_item.get(key) or "").strip()
        if value:
            return value
    return ""


def map_concur_invoice_line_to_allocation_row(
    line_item: dict[str, Any],
) -> dict[str, Any]:
    engagement = line_value(line_item, "Custom10", "Engagement")
    task = line_value(line_item, "Custom11", "Task")
    department = line_value(line_item, "Department", "Custom2")
    unit_price_raw = line_value(line_item, "UnitPrice", "Unit Price")
    quantity_raw = line_value(line_item, "Quantity")

    missing = [
        name
        for name, value in (
            ("Engagement", engagement),
            ("Task", task),
            ("UnitPrice", unit_price_raw),
            ("Department", department),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Missing required Concur invoice line fields for Maconomy "
            f"mapping: {', '.join(missing)}"
        )

    try:
        unit_price = float(Decimal(unit_price_raw) * 100)
    except (DecimalException, ValueError) as exc:
        raise ValueError(
            f"Unparseable Unit Price for unitpricecurrency: {unit_price_raw!r}"
        ) from exc

    try:
        quantity = float(quantity_raw) if quantity_raw else 1
    except ValueError as exc:
        raise ValueError(f"Unparseable Quantity for quantity: {quantity_raw!r}") from exc

    return {
        "data": {
            "accountnumber": "",
            "jobnumber": engagement,
            "taskname": task,
            "entrytext": "",
            "unitpricecurrency": unit_price,
            "numberof": quantity,
            "financevatcode": "",
            "locationname": "",
            "entityname": department,
        },
        "offset": 0,
        "limit": 100,
        "row": "end",
    }


__all__ = [
    "build_vendor_invoice_allocation_instance_payload",
    "build_vendor_invoice_table_init_payload",
    "line_value",
    "map_concur_invoice_line_to_allocation_row",
]
