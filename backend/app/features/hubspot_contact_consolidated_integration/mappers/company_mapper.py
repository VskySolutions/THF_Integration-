from typing import Any


COMPANY_FIELD_MAPPING: dict[str, str] = {
    "customernumber": "maconomy_customer_number",
    "name1": "name",
    "telephone": "phone",
    "country": "country",
    "zipcode": "zip",
    "name2": "address",
    "postaldistrict": "city",
    "name3": "address2",
}


class CompanyMapper:
    """Maconomy Customer Card -> HubSpot Company batch upsert payload."""

    def build_upsert_payload(
        self,
        customers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        inputs: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for customer in customers:
            customer_number = str(
                customer.get("customernumber") or ""
            ).strip()
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

            properties["maconomy_customer_number"] = customer_number

            inputs.append(
                {
                    "idProperty": "maconomy_customer_number",
                    "id": customer_number,
                    "objectWriteTraceId": f"company-{customer_number}",
                    "properties": properties,
                }
            )

        return {"inputs": inputs, "skipped": skipped}
