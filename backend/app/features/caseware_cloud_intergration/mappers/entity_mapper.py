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
        "EntityNo": "[VskyTesting]-002", #+ str(job_number),
        "Name": "[VskyTesting]-"+ str(job_name),
        "OwnerType": "Client",
        "CountryCode": "US",
        "OperatingName": "[VskyTesting]-Operating-002", #+ str(job_name),
        "OrganizationType": "Corporation",
        "Type": "A",
    }
