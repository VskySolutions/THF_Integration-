from typing import Any

DEFAULT_COUNTRY_NAME = "united_states_of_america"


def build_vendorcard_instance_payload() -> dict[str, Any]:
    return {
        "panes": {
            "card": {
                "fields": [
                    "entityname",
                    "attention",
                    "country",
                    "specification4name",
                    "electronicmailaddress",
                    "name1",
                    "name2",
                    "name3",
                    "postaldistrict",
                    "zipcode",
                    "telephone",
                    "vendornumber",
                    "currency",
                    "paymentmode",
                    "vatnumber",
                    "cnrnumber",
                    "disclosable",
                    "companynumber",
                    "parentvendor",
                    "linkingrulename",
                    "yourreference"
                ]
            }
        }
    }


def map_concur_vendor_to_maconomy_vendor_card(
    sap_vendor: dict[str, Any],
    country_names: dict[str, str],
) -> dict[str, Any]:
    vendor_code = str(sap_vendor.get("VendorCode") or "").strip()
    vendor_name = str(sap_vendor.get("VendorName") or "").strip()
    if not vendor_code:
        raise ValueError("VendorCode is empty")
    if not vendor_name:
        raise ValueError("VendorName is empty")

    first_name = str(sap_vendor.get("ContactFirstName") or "").strip()
    last_name = str(sap_vendor.get("ContactLastName") or "").strip()
    attention = " ".join(part for part in (first_name, last_name) if part)
    vat_number = str(sap_vendor.get("TaxID") or "").strip()
    account_number = str(sap_vendor.get("AccountNumber") or "").strip()

    sap_state = str(sap_vendor.get("State") or "").strip()
    country = country_names.get(sap_state.casefold()) if sap_state else None
    country = (
        country
        or country_names.get(DEFAULT_COUNTRY_NAME.casefold())
        or DEFAULT_COUNTRY_NAME
    )
    print("sap_state:", sap_state, "country:", country, "country_names:", country_names)
    data: dict[str, Any] = {
        "name1": vendor_name,
        "vendornumber": vendor_code,
        "name2": str(sap_vendor.get("Address1") or "").strip(),
        "name3": str(sap_vendor.get("Address2") or "").strip(),
        "postaldistrict": str(sap_vendor.get("City") or "").strip(),
        "zipcode": str(sap_vendor.get("PostalCode") or "").strip(),
        "country": country,
        "currency": "USD",
        "attention": attention,
        "electronicmailaddress": str(
            sap_vendor.get("ContactEmail") or ""
        ).strip(),
        "telephone": str(sap_vendor.get("ContactPhoneNumber") or "").strip(),
        # "companynumber": "100",
        "vatnumber": vat_number,
        "cnrnumber": vat_number if vat_number else "-",
        "disclosable": True,
        "paymentmode": "Centennial  THF Checking - Concur",
        "parentvendor": "TemplateVendor",
        "linkingrulename": "4",
        "yourreference": account_number
    }
    return {"data": data}
