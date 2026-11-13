from typing import Any

from app.features.hubspot_contact_consolidated_integration.constants import (
    PARENT_COMPANY_NAME_FIELD,
    PARENT_CUSTOMER_CSE_FIELD,
    PARENT_CUSTOMER_INDUSTRY_FIELD,
)

CONTACT_FIELD_MAPPING: dict[str, str] = {
    "contactpersonnumber": "maconomy_contact_person_number",
    "contactcompanynumber": "maconomy_customer_number",
    "electronicmailaddress": "email",
    "firstname": "firstname",
    "lastname": "lastname",
    "telephone": "phone",
    "position": "jobtitle",
    PARENT_COMPANY_NAME_FIELD: "company",
    PARENT_CUSTOMER_CSE_FIELD: "cse",
    PARENT_CUSTOMER_INDUSTRY_FIELD: "industry",
    "name2": "address",
    "name3": "street_address_2",
    "mobilephone": "mobilephone",
    "country": "country",
    "personaltitle": "name_prefix",
}


class ContactMapper:
    """Maconomy Contact Person -> HubSpot Contact batch upsert payload."""

    def enrich_contact(
        self,
        contact: dict[str, Any],
        parent_name: str | None,
        cse: str | None = None,
        industry: str | None = None,
    ) -> dict[str, Any]:
        """Return a copy enriched from the selected contact's parent Customer."""
        copy = {**contact}
        enrichments = {
            PARENT_COMPANY_NAME_FIELD: parent_name,
            PARENT_CUSTOMER_CSE_FIELD: cse,
            PARENT_CUSTOMER_INDUSTRY_FIELD: industry,
        }
        for field, value in enrichments.items():
            normalized_value = str(value or "").strip()
            if normalized_value:
                copy[field] = normalized_value
        return copy

    def enrich_contacts(
        self,
        contacts: list[dict[str, Any]],
        customer_name_by_number: dict[str, str],
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for contact in contacts:
            parent_number = str(
                contact.get("contactcompanynumber") or ""
            ).strip()
            parent_name = customer_name_by_number.get(parent_number)
            enriched.append(
                self.enrich_contact(contact, parent_name)
            )
        return enriched

    def build_upsert_payload(
        self,
        contacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        inputs: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for contact in contacts:
            contact_person_number = str(
                contact.get("contactpersonnumber") or ""
            ).strip()
            if not contact_person_number:
                skipped.append(
                    {
                        "record": contact,
                        "reason": "missing or empty contactpersonnumber",
                    }
                )
                continue

            properties: dict[str, str] = {}
            for maconomy_field, hubspot_property in CONTACT_FIELD_MAPPING.items():
                value = contact.get(maconomy_field)
                if value is None:
                    continue
                text = str(value).strip()
                if not text:
                    continue
                properties[hubspot_property] = text

            inputs.append(
                {
                    "idProperty": "maconomy_contact_person_number",
                    "id": contact_person_number,
                    "objectWriteTraceId": f"contact-{contact_person_number}",
                    "properties": properties,
                }
            )

        return {"inputs": inputs, "skipped": skipped}
