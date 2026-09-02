from typing import Any


def map_maconomy_customer_to_caseware_address(
    customer_data: dict[str, Any],
    entity_cw_guid: str,
    entity_cw_owner_id: int,
) -> dict[str, Any]:
    if not entity_cw_guid:
        raise ValueError("Caseware entity CWGuid is required")
    if not isinstance(entity_cw_owner_id, int):
        raise ValueError("Caseware entity owner ID must be an integer")

    return {
        "Id": 0,
        "Address1": customer_data.get("name2", ""),
        "City": customer_data.get("postaldistrict", ""),
        "Country": customer_data.get("country", ""),
        "Name": customer_data.get("name1", ""),
        "AddressCategory": "Business",
        "OwnerCWGuid": entity_cw_guid,
        "OwnerId": entity_cw_owner_id,
    }


def map_maconomy_job_to_caseware_address_update(
    job_data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "Address1": job_data.get("name2", ""),
        "AddressCategory": "Business",
        "City": job_data.get("postaldistrict", ""),
        "Country": job_data.get("country", ""),
        "Name": job_data.get("name1", ""),
    }
