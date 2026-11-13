from typing import Any


SPECIFICATION1_DESCRIPTION_FIELD = "specification1_description"

COMPANY_FIELD_MAPPING: dict[str, str] = {
    "customernumber": "maconomy_customer_number",
    "name1": "name",
    "telephone": "phone",
    "country": "country",
    "zipcode": "zip",
    "name2": "address",
    "postaldistrict": "city",
    "name3": "address2",
    "theaccountmanagername": "cse",
    SPECIFICATION1_DESCRIPTION_FIELD: "industry",
}


class CompanyMapper:
    """Maconomy Customer Card -> HubSpot Company batch upsert payload."""

    @staticmethod
    def enrich_customer(
        customer: dict[str, Any],
        specification1_descriptions: dict[str, str],
    ) -> dict[str, Any]:
        """Resolve the Customer's Specification 1 description for Industry."""
        enriched = {**customer}
        specification1_name = str(
            customer.get("specification1name") or ""
        ).strip()
        industry = str(
            specification1_descriptions.get(specification1_name) or ""
        ).strip()
        if industry:
            enriched[SPECIFICATION1_DESCRIPTION_FIELD] = industry
        return enriched

    def enrich_customers(
        self,
        customers: list[dict[str, Any]],
        specification1_descriptions: dict[str, str],
    ) -> list[dict[str, Any]]:
        return [
            self.enrich_customer(customer, specification1_descriptions)
            for customer in customers
        ]

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
