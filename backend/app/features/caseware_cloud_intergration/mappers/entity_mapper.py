from typing import Any


def map_maconomy_job_to_caseware_entity(
    job_data: dict[str, Any],
) -> dict[str, Any]:
    job_number = job_data.get("jobnumber")
    job_name = job_data.get("jobname")

    if not job_number or not job_name:
        raise ValueError("Maconomy jobnumber and jobname are required")

    return {
        "Id": 0,
        "EntityNo": f"Vsky-{str(job_number)}",
        "Name": str(job_name),
        "OwnerType": "Client",
        "CountryCode": "US",#job_data.get("country", "US"),
        "OperatingName": str(job_name),
        "OrganizationType": "Corporation",
        "Type": "A",
    }


def map_maconomy_job_to_caseware_entity_update(
    job_data: dict[str, Any],
    current_entity: dict[str, Any],
) -> dict[str, Any]:
    job_number = job_data.get("jobnumber")
    job_name = job_data.get("jobname")
    print(job_data)
    return {
        "EntityNo": f"Vsky-{str(job_number)}",
        "Name": str(job_name),
        "OwnerType": "Client",
        "Type": "A",
    }
