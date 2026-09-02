from typing import Any


def map_maconomy_job_to_cch_client(
    job_data: dict[str, Any],
) -> dict[str, Any]:
    job_number = job_data.get("jobnumber")
    job_name = job_data.get("jobname")
    group_name = job_data.get("companyname")
    group_number = job_data.get("companynumber")
    primary_task = job_data.get("jobgroup")
    branch_name = job_data.get("departmentnumber")
    fiscal_year = job_data.get("theyear")
    phone_number = job_data.get("telephone")
    email_id = job_data.get("electronicmailaddress")
    active = not job_data.get("closed", False) # String
    clientType = job_data.get("crmjobtype")  # Assuming this is the correct field for generation type - name5
    generationType = job_data.get("name5")  # Assuming this is the correct field for generation type - name5


    if not job_number or not job_name:
        raise ValueError("Maconomy jobnumber and jobname are required")

    return {
        "clientType": str(clientType),
        "accountNumber": f"-{str(job_number)}",
        "firstName": str(job_name),
        "middleName": str(job_name),
        "last_CorporateName": str(job_name), # last_Entity_Name
        "generationType": str(generationType),
        "emailId": str(email_id),
        "phoneNumber": str(phone_number),
        # "branchName": str(branch_name),
        "groupName": str(group_name),
        # "groupNumber": str(group_number),
        "primaryTask": str(primary_task),
        "fiscalYear": str(fiscal_year),
        "active": active,
    }