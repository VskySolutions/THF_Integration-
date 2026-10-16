"""Dynamic Maconomy -> HubSpot field mapping.

Maps Maconomy Customer Card records (from ``classify_customers`` create/update
lists) into HubSpot batch upsert payloads for Companies and Contacts.
Separate from the static verified-payload mappers (``company_mapper``,
``contact_mapper``), which remain untouched.

Company side: one input per customer record, keyed by ``customernumber``
(``idProperty="maconomy_customer_number"``).
Contact side: flattens each customer's nested ``contactperson`` array, one
input per contact, keyed by ``contactpersonnumber``
(``idProperty="contactpersonnumber"``). The contact's ``contactcompanynumber``
(== parent ``customernumber``) is carried as ``maconomy_customer_number``.

Not yet wired into the sync flow (Req[#20] FR-8); a later requirement
consumes these functions.
"""

from typing import Any


COMPANY_FIELD_MAPPING: dict[str, str] = {
    "customernumber": "maconomy_customer_number",
    "name1": "name",
    "telephone": "phone",
    "country": "country",
    "zipcode": "postalcode",
    "name2": "sheetaddress",
    "postaldistrict": "city",
}

CONTACT_FIELD_MAPPING: dict[str, str] = {
    "contactpersonnumber": "maconomy_contact_person_number",
    "contactcompanynumber": "maconomy_customer_number",
    "electronicmailaddress": "email",
    "firstname": "firstname",
    "lastname": "lastname",
    "telephone": "phone",
    "position": "jobtitle",
}


def map_customers_to_company_upsert(
    create_customers: list[dict[str, Any]],
    update_customers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the HubSpot company upsert payload from create/update customers.

    ``create`` and ``update`` are mapped identically. Records with a
    missing/empty ``customernumber`` cannot be upserted and are reported
    under ``skipped``. Empty/None Maconomy values are omitted from
    ``properties``.

    Returns ``{"inputs": [...], "skipped": [...]}``.
    """
    inputs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for customer in [*create_customers, *update_customers]:
        customer_number = str(customer.get("customernumber") or "").strip()
        if not customer_number:
            skipped.append(
                {
                    "record": customer,
                    "reason": "missing or empty customernumber",
                }
            )
            continue

        properties: dict[str, str] = {}
        for maconomy_field, hubspot_property in COMPANY_FIELD_MAPPING.items():
            value = customer.get(maconomy_field)
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            properties[hubspot_property] = text

        # Mirror the verified payload: the id key is also a property.
        properties["maconomy_customer_number"] = customer_number

        inputs.append(
            {
                "idProperty": "maconomy_customer_number",
                "id": customer_number,
                "properties": properties,
            }
        )

    return {"inputs": inputs, "skipped": skipped}


def map_customers_to_contact_upsert(
    create_customers: list[dict[str, Any]],
    update_customers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the HubSpot contact upsert payload from create/update customers.

    Flattens each customer's nested ``contactperson`` array; a customer with
    a missing/empty array simply contributes no inputs. ``create`` and
    ``update`` are mapped identically. Contacts with a missing/empty
    ``contactpersonnumber`` are reported under ``skipped``. Empty/None
    Maconomy values are omitted from ``properties``.

    Returns ``{"inputs": [...], "skipped": [...]}``.
    """
    inputs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for customer in [*create_customers, *update_customers]:
        contactpersons = customer.get("contactperson") or []

        for contact in contactpersons:
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
            for (
                maconomy_field,
                hubspot_property,
            ) in CONTACT_FIELD_MAPPING.items():
                value = contact.get(maconomy_field)
                if value is None:
                    continue
                text = str(value).strip()
                if not text:
                    continue
                properties[hubspot_property] = text

            # Mirror the company pattern: the id key is also a property.

            inputs.append(
                {
                    "idProperty": "maconomy_contact_person_number",
                    "id": contact_person_number,
                    "properties": properties,
                }
            )

    return {"inputs": inputs, "skipped": skipped}
