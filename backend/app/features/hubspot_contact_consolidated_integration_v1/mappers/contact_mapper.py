"""Map selected Maconomy master Contact Persons to HubSpot Contacts."""

from typing import Any


CONTACT_FIELD_MAPPING: dict[str, str] = {
    "contactpersonnumber": "maconomy__contact_person_number",
    "contactcompanynumber": "maconomy_customer_number",
    "electronicmailaddress": "email",
    "firstname": "firstname",
    "lastname": "lastname",
    "telephone": "phone",
    "position": "jobtitle",
    "name2": "address",
    "name3": "street_address_2",
    "mobilephone": "mobilephone",
    "country": "country",
    "personaltitle": "name_prefix",
}


class ContactMapper:
    """Build one batch upsert input per selected master."""

    @staticmethod
    def build_upsert_payload(masters: list[dict[str, Any]]) -> dict[str, Any]:
        inputs: list[dict[str, Any]] = []
        skipped: list[dict[str, str | None]] = []
        seen_numbers: set[str] = set()
        for master in masters:
            number = str(master.get("contactpersonnumber") or "").strip()
            email = str(master.get("electronicmailaddress") or "").strip()
            if not number or not email:
                skipped.append(
                    {
                        "source_id": number or None,
                        "reason": "missing contactpersonnumber or email",
                    }
                )
                continue
            if number in seen_numbers:
                skipped.append(
                    {"source_id": number, "reason": "duplicate master contact number"}
                )
                continue
            seen_numbers.add(number)

            properties: dict[str, str] = {}
            for maconomy_field, hubspot_property in CONTACT_FIELD_MAPPING.items():
                value = master.get(maconomy_field)
                text = str(value).strip() if value is not None else ""
                properties[hubspot_property] = text
            inputs.append(
                {
                    "idProperty": "maconomy__contact_person_number",
                    "id": number,
                    "objectWriteTraceId": f"contact-{number}",
                    "properties": properties,
                }
            )
        return {"inputs": inputs, "skipped": skipped}
