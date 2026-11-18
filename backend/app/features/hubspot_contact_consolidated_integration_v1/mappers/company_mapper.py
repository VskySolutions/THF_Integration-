"""Map Maconomy Customer Cards to HubSpot Company batch inputs."""

from typing import Any


COMPANY_FIELD_MAPPING: dict[str, str] = {
    "customernumber": "maconomy_customer_number",
    "name1": "name",
    "telephone": "phone",
    "country": "country",
    "zipcode": "zip",
    "name2": "address",
    "postaldistrict": "city",
    "name3": "street_address_2",
    "theaccountmanagername": "cse",
}

HUBSPOT_INDUSTRY_BY_SPECIFICATION1_DESCRIPTION: dict[str, str] = {}


class CompanyMapper:
    """Build Company inputs keyed by the Maconomy customer number."""

    @staticmethod
    def build_upsert_payload(
        customers: list[dict[str, Any]],
        specification1_descriptions: dict[str, str],
    ) -> dict[str, Any]:
        inputs: list[dict[str, Any]] = []
        skipped: list[dict[str, str | None]] = []
        seen_numbers: set[str] = set()

        for customer in customers:
            customer_number = str(customer.get("customernumber") or "").strip()
            if not customer_number:
                skipped.append(
                    {
                        "source_id": None,
                        "reason": "missing or empty customernumber",
                    }
                )
                continue
            if customer_number in seen_numbers:
                skipped.append(
                    {
                        "source_id": customer_number,
                        "reason": "duplicate customernumber in discovery result",
                    }
                )
                continue
            seen_numbers.add(customer_number)

            properties: dict[str, str] = {}
            for maconomy_field, hubspot_property in COMPANY_FIELD_MAPPING.items():
                value = customer.get(maconomy_field)
                text = str(value).strip() if value is not None else ""
                if text:
                    properties[hubspot_property] = text

            specification1_name = str(
                customer.get("specification1name") or ""
            ).strip()
            specification1_description = str(
                specification1_descriptions.get(specification1_name) or ""
            ).strip()
            industry: str | None = (
                HUBSPOT_INDUSTRY_BY_SPECIFICATION1_DESCRIPTION.get(
                    specification1_description
                )
            )
            if industry is not None:
                properties["industry"] = industry

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
