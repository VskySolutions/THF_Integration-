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
    """Build Maconomy name1 as LastName,FirstName M."""

    first_name = (
        _normalize_optional_string(
            employee_data.get("firstName")
        )
        or ""
    )

    middle_name = (
        _normalize_optional_string(
            employee_data.get("middleName")
        )
        or ""
    )

    last_name = (
        _normalize_optional_string(
            employee_data.get("lastName")
        )
        or ""
    )

    middle_initial = (
        middle_name[0]
        if middle_name
        else ""
    )

    given_name = first_name

    if middle_initial:
        given_name = (
            f"{given_name} {middle_initial}".strip()
        )

    if last_name and given_name:
        return f"{last_name},{given_name}"

    return last_name or given_name

def _build_maconomy_name1(
    employee_data: dict[str, Any],
) -> str | None:
    """Build Maconomy name1 as lastname,firstname."""

    first_name = _normalize_optional_string(
        employee_data.get("firstName")
    )

    last_name = _normalize_optional_string(
        employee_data.get("lastName")
    )

    if first_name and last_name:
        return f"{last_name},{first_name}"

    if last_name:
        return last_name

    if first_name:
        return first_name

    return None

def map_paycor_employee(
    employee_data: dict[str, Any],
    *,
    departments_by_id: dict[
        str,
        dict[str, Any],
    ],
) -> dict[str, Any]:
    """Map one Paycor employee into normalized integration data.

    Required fields:
    - Paycor employee UUID
    - Employee number
    - Legal entity ID
    - Country

    All other fields are optional.
    """

    # Supports both the raw Paycor response and already
    # normalized employee data.
    employee_id_value = (
        employee_data.get("id")
        or employee_data.get("paycorEmployeeId")
    )

    paycor_employee_id = _parse_employee_id(
        employee_id_value
    )

    employee_number = _normalize_required_string(
        employee_data.get("employeeNumber"),
        "employee number",
    )

    # Legal entity ID is required.
    legal_entity_data = employee_data.get(
        "legalEntity"
    )

    if isinstance(legal_entity_data, dict):
        legal_entity_id_value = (
            legal_entity_data.get("id")
        )
    else:
        legal_entity_id_value = (
            employee_data.get("legalEntityId")
        )

    legal_entity_id = _parse_legal_entity_id(
        legal_entity_id_value
    )

    # Names are optional.
    first_name = _normalize_optional_string(
        employee_data.get("firstName")
    )

    middle_name = _normalize_optional_string(
        employee_data.get("middleName")
    )

    last_name = _normalize_optional_string(
        employee_data.get("lastName")
    )

    full_name = _build_full_name(employee_data)

    # Build full name only when Paycor did not provide it.
    if full_name is None:
        name_parts = [
            value
            for value in (
                first_name,
                middle_name,
                last_name,
            )
            if value
        ]

        full_name = (
            " ".join(name_parts)
            if name_parts
            else None
        )

    # Email is optional.
    email_data = employee_data.get("email")

    if isinstance(email_data, dict):
        email_address = (
            _normalize_optional_string(
                email_data.get("emailAddress")
            )
        )
    else:
        email_address = (
            _normalize_optional_string(
                employee_data.get("emailAddress")
            )
        )

    
    # temporarily
    
    # if email_address:
        # email_address = f"{email_address}.test"

    # Employment date is optional.
    employment_date_data = employee_data.get(
        "employmentDateData"
    )

    hire_date_value: str | None = None

    if isinstance(employment_date_data, dict):
        hire_date_value = (
            _normalize_optional_string(
                employment_date_data.get(
                    "hireDate"
                )
            )
        )

    if hire_date_value is None:
        hire_date_value = (
            _normalize_optional_string(
                employee_data.get("hireDate")
            )
        )

    hire_date: str | None = None

    if hire_date_value is not None:
        hire_date = _parse_paycor_date(
            hire_date_value,
            "hire date",
        ).isoformat()

    # Position and manager are optional.
    position_data = employee_data.get(
        "positionData"
    )

    job_title: str | None = None
    job_code: str | None = None
    manager_employee_id: str | None = None
    manager_employee_number: str | None = None

    if isinstance(position_data, dict):
        job_title = _normalize_optional_string(
            position_data.get("jobTitle")
        )

        job_code = _normalize_optional_string(
            position_data.get("jobCode")
        )

        manager_data = position_data.get(
            "manager"
        )

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
    else:
        # Supports already normalized data.
        job_title = _normalize_optional_string(
            employee_data.get("position")
        )

        job_code = _normalize_optional_string(
            employee_data.get("jobCode")
        )

        manager_employee_id = (
            _normalize_optional_string(
                employee_data.get(
                    "managerEmployeeId"
                )
            )
        )

        manager_employee_number = (
            _normalize_optional_string(
                employee_data.get(
                    "managerEmployeeNumber"
                )
            )
        )

    # Work-location ID and name are optional,
    # but country is required.
    work_location_data = employee_data.get(
        "workLocation"
    )

    work_location_id: str | None = None
    work_location_name: str | None = None
    work_location_country: str | None = None

    if isinstance(work_location_data, dict):
        work_location_id = (
            _normalize_optional_string(
                work_location_data.get("id")
            )
        )

        work_location_name = (
            _normalize_optional_string(
                work_location_data.get("name")
            )
        )

        work_location_country = (
            _normalize_optional_string(
                work_location_data.get("country")
            )
        )

    # Supports already normalized data or a top-level
    # Paycor country value.
    if work_location_id is None:
        work_location_id = (
            _normalize_optional_string(
                employee_data.get(
                    "workLocationId"
                )
            )
        )

    if work_location_name is None:
        work_location_name = (
            _normalize_optional_string(
                employee_data.get(
                    "workLocationName"
                )
            )
        )

    if work_location_country is None:
        work_location_country = (
            _normalize_optional_string(
                employee_data.get(
                    "workLocationCountry"
                )
            )
            or _normalize_optional_string(
                employee_data.get("country")
            )
        )

    if work_location_country is None:
        raise ValueError(
            "Paycor country is required"
        )

    # Department is completely optional.
    department_id: str | None = None
    department_name: str | None = None
    department_number: str | None = None

    department_reference = employee_data.get(
        "department"
    )

    if isinstance(department_reference, dict):
        department_id = (
            _normalize_optional_string(
                department_reference.get("id")
            )
        )
    else:
        department_id = (
            _normalize_optional_string(
                employee_data.get("departmentId")
            )
        )

    if department_id is not None:
        department_data = departments_by_id.get(
            department_id
        )

        if isinstance(department_data, dict):
            department_name = (
                _normalize_optional_string(
                    department_data.get(
                        "description"
                    )
                )
            )

            department_number = (
                _normalize_optional_string(
                    department_data.get("code")
                )
            )

    # Supports already normalized department values.
    if department_name is None:
        department_name = (
            _normalize_optional_string(
                employee_data.get(
                    "departmentName"
                )
            )
        )

    if department_number is None:
        department_number = (
            _normalize_optional_string(
                employee_data.get(
                    "departmentNumber"
                )
            )
        )

    # Prefix and suffix come from:
    # /v1/tenants/{tenantId}/persons/{employeeUuid}
    prefix = _normalize_optional_string(
        employee_data.get("prefix")
    )

    suffix = _normalize_optional_string(
        employee_data.get("suffix")
    )

    return {
        "paycorEmployeeId": paycor_employee_id,
        "employeeNumber": employee_number,
        "legalEntityId": legal_entity_id,
        "firstName": first_name,
        "middleName": middle_name,
        "lastName": last_name,
        "fullName": full_name,
        "prefix": prefix,
        "suffix": suffix,
        "emailAddress": email_address,
        "hireDate": hire_date,
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
    *,
    include_name_components: bool = False,
) -> dict[str, Any]:
    """Map normalized Paycor employee data to Maconomy fields."""

    employee_number = _normalize_required_string(
        employee_data.get("employeeNumber"),
        "employee number",
    )

    paycor_employee_id = _parse_employee_id(
        employee_data.get("paycorEmployeeId")
    )

    # Required for integration/mapping records, although it
    # is not currently submitted as a Maconomy field.
    _parse_legal_entity_id(
        employee_data.get("legalEntityId")
    )

    work_location_country = (
        _normalize_required_string(
            employee_data.get(
                "workLocationCountry"
            ),
            "country",
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

    # These are the only values always submitted.
    maconomy_data: dict[str, Any] = {
        "employeenumber": employee_number,
        "country": maconomy_country,

        # Paycor employee UUID is now stored in text9.
        "text9": paycor_employee_id,
    }

    # Optional string fields. Blank values are omitted.
    optional_field_mapping = {
        
        "emailAddress": (
            "electronicmailaddress"
        ),
        "position": "position",
        "workLocationName": (
            "specification4name"
        ),
        "prefix": "personaltitle",
        "suffix": "text10",
    }
    if include_name_components:
        optional_field_mapping.update(
            {
                "firstName": "firstname",
                "middleName": "middlename",
                "lastName": "lastname",
            }
        )
    
    name1 = _build_full_name(
        employee_data
    )

    if name1 is not None:
        maconomy_data["name1"] = name1

    for (
        paycor_field,
        maconomy_field,
    ) in optional_field_mapping.items():
        value = _normalize_optional_string(
            employee_data.get(paycor_field)
        )

        if value is not None:
            maconomy_data[
                maconomy_field
            ] = value

    # Hire date is optional, but when provided it must
    # contain a valid Paycor date.
    hire_date_value = (
        _normalize_optional_string(
            employee_data.get("hireDate")
        )
    )

    if hire_date_value is not None:
        date_employed = _parse_paycor_date(
            hire_date_value,
            "hire date",
        )

        maconomy_data["dateemployed"] = (
            date_employed.isoformat()
        )

    # The service must ensure this manager already exists
    # in Maconomy before leaving this value populated.
    manager_employee_number = (
        _normalize_optional_string(
            employee_data.get(
                "managerEmployeeNumber"
            )
        )
    )

    if manager_employee_number is not None:
        maconomy_data[
            "superioremployee"
        ] = manager_employee_number

    return {
    "data": maconomy_data,
}
    
    
    

# update employee
MACONOMY_EMPLOYEE_UPDATE_FIELDS = (
    "name1",
    "country",
    "dateemployed",
    "electronicmailaddress",
    "position",
)


def map_paycor_employee_to_maconomy_update(
    employee_data: dict[str, Any],
) -> dict[str, Any]:
    """Map only fields currently approved for employee updates."""

    mapped_payload = map_paycor_employee_to_maconomy(
        employee_data
    )

   
    nested_data = mapped_payload.get("data")

    mapped_data = (
        nested_data
        if isinstance(nested_data, dict)
        else mapped_payload
    )

    return {
        field_name: mapped_data[field_name]
        for field_name in MACONOMY_EMPLOYEE_UPDATE_FIELDS
        if field_name in mapped_data
    }