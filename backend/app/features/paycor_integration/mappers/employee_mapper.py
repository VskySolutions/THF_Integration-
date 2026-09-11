"""Map Paycor employee records to integration and Maconomy data."""

import uuid
from datetime import date
from typing import Any


# Add other country mappings only after confirmation.
PAYCOR_TO_MACONOMY_COUNTRY = {
    "USA": "united_states_of_america",
}


def _normalize_optional_string(
    value: Any,
) -> str | None:
    if not isinstance(value, str):
        return None

    normalized_value = value.strip()
    return normalized_value or None


def _normalize_required_string(
    value: Any,
    field_name: str,
) -> str:
    normalized_value = _normalize_optional_string(
        value
    )

    if normalized_value is None:
        raise ValueError(
            f"Paycor {field_name} is required"
        )

    return normalized_value


def _parse_paycor_date(
    value: str,
    field_name: str,
) -> date:
    try:
        return date.fromisoformat(
            value.strip()[:10]
        )

    except ValueError as exc:
        raise ValueError(
            f"Paycor {field_name} is invalid"
        ) from exc


def _parse_employee_id(
    value: Any,
) -> str:
    employee_id = _normalize_required_string(
        value,
        "employee ID",
    )

    try:
        return str(uuid.UUID(employee_id))

    except ValueError as exc:
        raise ValueError(
            "Paycor employee ID must be a valid UUID"
        ) from exc


def _parse_legal_entity_id(
    value: Any,
) -> int:
    if isinstance(value, bool):
        raise ValueError(
            "Paycor legal entity ID is invalid"
        )

    try:
        legal_entity_id = int(
            str(value).strip()
        )

    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Paycor legal entity ID must be an integer"
        ) from exc

    if legal_entity_id <= 0:
        raise ValueError(
            "Paycor legal entity ID must be positive"
        )

    return legal_entity_id


def _build_full_name(
    employee_data: dict[str, Any],
) -> str:
    name_parts = [
        _normalize_optional_string(
            employee_data.get("firstName")
        ),
        _normalize_optional_string(
            employee_data.get("middleName")
        ),
        _normalize_optional_string(
            employee_data.get("lastName")
        ),
    ]

    full_name = " ".join(
        part
        for part in name_parts
        if part is not None
    )

    if not full_name:
        raise ValueError(
            "Paycor employee name is required"
        )

    return full_name


def map_paycor_employee(
    employee_data: dict[str, Any],
    *,
    departments_by_id: dict[
        str,
        dict[str, Any],
    ],
) -> dict[str, Any]:
    """Map one Paycor employee into normalized integration data."""

    paycor_employee_id = _parse_employee_id(
        employee_data.get("id")
    )

    employee_number = _normalize_required_string(
        employee_data.get("employeeNumber"),
        "employee number",
    )

    full_name = _build_full_name(
        employee_data
    )

    legal_entity_data = employee_data.get(
        "legalEntity"
    )

    if not isinstance(legal_entity_data, dict):
        raise ValueError(
            "Paycor legal entity data is required"
        )

    legal_entity_id = _parse_legal_entity_id(
        legal_entity_data.get("id")
    )

    employment_date_data = employee_data.get(
        "employmentDateData"
    )

    if not isinstance(
        employment_date_data,
        dict,
    ):
        raise ValueError(
            "Paycor employment-date data is required"
        )

    hire_date_value = _normalize_required_string(
        employment_date_data.get("hireDate"),
        "hire date",
    )

    hire_date = _parse_paycor_date(
        hire_date_value,
        "hire date",
    )

    email_data = employee_data.get("email")

    email_address = (
        _normalize_optional_string(
            email_data.get("emailAddress")
        )
        if isinstance(email_data, dict)
        else None
    )
    # email_address= f"{email_address}.test"     #testing
    

    position_data = employee_data.get(
        "positionData"
    )

    if not isinstance(position_data, dict):
        raise ValueError(
            "Paycor position data is required"
        )

    job_title = _normalize_required_string(
        position_data.get("jobTitle"),
        "job title",
    )

    job_code = _normalize_optional_string(
        position_data.get("jobCode")
    )

    manager_data = position_data.get(
        "manager"
    )

    manager_employee_id: str | None = None
    manager_employee_number: str | None = None

    if isinstance(manager_data, dict):
        manager_employee_id = (
            _normalize_optional_string(
                manager_data.get("id")
            )
        )

        manager_employee_number = (
            _normalize_optional_string(
                manager_data.get(
                    "employeeNumber"
                )
            )
        )

    work_location_data = employee_data.get(
        "workLocation"
    )

    if not isinstance(
        work_location_data,
        dict,
    ):
        raise ValueError(
            "Paycor work-location data is required"
        )

    work_location_id = (
        _normalize_required_string(
            work_location_data.get("id"),
            "work-location ID",
        )
    )

    work_location_name = (
        _normalize_required_string(
            work_location_data.get("name"),
            "work-location name",
        )
    )

    work_location_country = (
        _normalize_required_string(
            work_location_data.get("country"),
            "work-location country",
        )
    )

    department_reference = employee_data.get(
        "department"
    )

    if not isinstance(
        department_reference,
        dict,
    ):
        raise ValueError(
            "Paycor department data is required"
        )

    department_id = _normalize_required_string(
        department_reference.get("id"),
        "department ID",
    )

    department_data = departments_by_id.get(
        department_id
    )

    if department_data is None:
        raise ValueError(
            "Paycor department was not found: "
            f"{department_id}"
        )

    department_name = (
        _normalize_required_string(
            department_data.get("description"),
            "department description",
        )
    )

    department_number = (
        _normalize_required_string(
            department_data.get("code"),
            "department code",
        )
    )

    return {
        "paycorEmployeeId": paycor_employee_id,
        "employeeNumber": employee_number,
        "legalEntityId": legal_entity_id,
        "firstName": _normalize_optional_string(
            employee_data.get("firstName")
        ),
        "middleName": _normalize_optional_string(
            employee_data.get("middleName")
        ),
        "lastName": _normalize_optional_string(
            employee_data.get("lastName")
        ),
        "fullName": full_name,
        "emailAddress": email_address,
        "hireDate": hire_date.isoformat(),
        "position": job_title,
        "jobCode": job_code,
        "departmentId": department_id,
        "department": department_name,
        "departmentNumber": department_number,
        "workLocationId": work_location_id,
        "workLocationName": work_location_name,
        "workLocationCountry": (
            work_location_country
        ),
        "managerEmployeeId": (
            manager_employee_id
        ),
        "managerEmployeeNumber": (
            manager_employee_number
        ),
    }


def map_paycor_employee_to_maconomy(
    employee_data: dict[str, Any],
) -> dict[str, Any]:
    """Map normalized Paycor data into a Maconomy payload."""

    employee_number = _normalize_required_string(
        employee_data.get("employeeNumber"),
        "employee number",
    )
    
    paycor_employee_id = _parse_employee_id(
        employee_data.get("paycorEmployeeId")
)

    full_name = _normalize_required_string(
        employee_data.get("fullName"),
        "employee name",
    )

    hire_date_value = _normalize_required_string(
        employee_data.get("hireDate"),
        "hire date",
    )

    date_employed = _parse_paycor_date(
        hire_date_value,
        "hire date",
    )

    work_location_country = (
        _normalize_required_string(
            employee_data.get(
                "workLocationCountry"
            ),
            "work-location country",
        )
    )

    paycor_country = (
        work_location_country.upper()
    )

    maconomy_country = (
        PAYCOR_TO_MACONOMY_COUNTRY.get(
            paycor_country
        )
    )

    if maconomy_country is None:
        raise ValueError(
            "Unsupported Paycor country: "
            f"{work_location_country}"
        )

    position = _normalize_required_string(
        employee_data.get("position"),
        "position",
    )

    

    email_address = _normalize_optional_string(
        employee_data.get("emailAddress")
    )

    manager_employee_number = (
        _normalize_optional_string(
            employee_data.get(
                "managerEmployeeNumber"
            )
        )
    )

    maconomy_data: dict[str, Any] = {
        "employeenumber": employee_number,
        "name1": full_name,
        "dateemployed": (date_employed.isoformat()),
        "country": maconomy_country,
        "position": position,
        "text10": paycor_employee_id,
    }

    if email_address is not None:
        maconomy_data[
            "electronicmailaddress"
        ] = email_address

    if manager_employee_number is not None:
        maconomy_data[
            "superioremployee"
        ] = manager_employee_number

    return {
    "data": maconomy_data,
}