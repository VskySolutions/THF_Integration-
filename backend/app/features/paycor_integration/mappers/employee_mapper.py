from typing import Any


def map_paycor_employee(
    employee_data: dict[str, Any],
) -> dict[str, Any]:
    onboarding_employee_id = employee_data.get(
        "onboardingEmployeeId"
    )
    employee_number = employee_data.get(
        "employeeNumber"
    )
    legal_entity_id = employee_data.get(
        "legalEntityId"
    )

    if (
        not isinstance(onboarding_employee_id, str)
        or not onboarding_employee_id.strip()
    ):
        raise ValueError(
            "Paycor onboarding employee ID is required"
        )
    if employee_number is None:
        raise ValueError(
            "Paycor employee number is required"
        )

    if (
        not isinstance(employee_number, (int, str))
        or isinstance(employee_number, bool)
        or not str(employee_number).strip()
    ):
        raise ValueError(
            "Paycor employee number must be valid"
        )

    if (
        not isinstance(legal_entity_id, int)
        or isinstance(legal_entity_id, bool)
    ):
        raise ValueError(
            "Paycor legal entity ID must be an integer"
        )

    return {
        "onboardingEmployeeId": onboarding_employee_id,
        "employeeNumber": employee_number,
        "legalEntityId": legal_entity_id,
        "firstName": employee_data.get(
            "firstName"
        ),
        "lastName": employee_data.get(
            "lastName"
        ),
        "fullName": employee_data.get(
            "fullName"
        ),
        "emailAddress": employee_data.get(
            "emailAddress"
        ),
        "hireDate": employee_data.get(
            "hireDate"
        ),
        "workLocation": employee_data.get(
            "workLocation"
        ),
        "workLocationId": employee_data.get(
            "workLocationId"
        ),
        "manager": employee_data.get(
            "manager"
        ),
        "managerId": employee_data.get(
            "managerId"
        ),
    }