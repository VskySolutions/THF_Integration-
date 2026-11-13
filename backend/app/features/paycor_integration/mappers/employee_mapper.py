"""Map Paycor employee records to integration and Maconomy data."""

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any


US_COUNTRY_ALIASES = {
    "us",
    "usa",
    "united states",
}

ADDRESS_FIELD_MAPPING = {
    "streetLine1": "name2",
    "city": "postaldistrict",
    "zipCode": "zipcode",
}

WEEKDAY_FIXED_WORKING_TIME_FIELDS = (
    "fixedworkingtimemonday",
    "fixedworkingtimetuesday",
    "fixedworkingtimewednesday",
    "fixedworkingtimethursday",
    "fixedworkingtimefriday",
)

WEEKEND_FIXED_WORKING_TIME_FIELDS = (
    "fixedworkingtimesaturday",
    "fixedworkingtimesunday",
)

FIXED_WORKING_TIME_FIELDS = (
    *WEEKDAY_FIXED_WORKING_TIME_FIELDS,
    *WEEKEND_FIXED_WORKING_TIME_FIELDS,
)


class EmployeeAddressMappingError(ValueError):
    """Raised when an employee address cannot resolve a country."""


class EmployeeAnnualHoursMappingError(ValueError):
    """Raised when annual hours cannot produce a weekly schedule."""


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


def map_paycor_primary_address(
    employee_data: dict[str, Any],
    *,
    countries_by_alias: dict[str, str],
) -> dict[str, str]:
    """Map one matched Paycor Primary address to Maconomy fields."""

    person_error = _normalize_optional_string(
        employee_data.get("personAddressError")
    )

    if person_error is not None:
        raise EmployeeAddressMappingError(person_error)

    person_id = _normalize_optional_string(
        employee_data.get("personId")
    )

    if person_id is None:
        raise EmployeeAddressMappingError(
            "Paycor employee person ID is required for address mapping"
        )

    primary_address = employee_data.get("primaryAddress")

    if not isinstance(primary_address, dict):
        raise EmployeeAddressMappingError(
            "Paycor Primary address is required"
        )

    paycor_country = _normalize_optional_string(
        primary_address.get("country")
    )

    if paycor_country is None:
        raise EmployeeAddressMappingError(
            "Paycor Primary address country is required"
        )

    if paycor_country.casefold() in US_COUNTRY_ALIASES:
        resolved_country = _normalize_optional_string(
            primary_address.get("state")
        )

        if resolved_country is None:
            raise EmployeeAddressMappingError(
                "Paycor Primary address state is required for a US address"
            )
    else:
        resolved_country = paycor_country

    maconomy_country = countries_by_alias.get(
        " ".join(resolved_country.split()).casefold()
    )

    if maconomy_country is None:
        raise EmployeeAddressMappingError(
            "No Maconomy Country matches Paycor address value "
            f"{resolved_country!r}"
        )

    mapped_address: dict[str, str] = {
        "country": maconomy_country,
        "name5": "",
    }

    for paycor_field, maconomy_field in (
        ADDRESS_FIELD_MAPPING.items()
    ):
        value = _normalize_optional_string(
            primary_address.get(paycor_field)
        )

        if value is not None:
            mapped_address[maconomy_field] = value

    street_line_2 = (
        _normalize_optional_string(
            primary_address.get("streetLine2")
        )
        or _normalize_optional_string(
            primary_address.get("suite")
        )
    )

    if street_line_2 is not None:
        mapped_address["name3"] = street_line_2

    return mapped_address


def map_annual_hours_to_fixed_working_time(
    employee_data: dict[str, Any],
) -> dict[str, int]:
    """Divide annual hours by 260 and round each weekday up."""

    annual_hours_value = employee_data.get("annualHours")

    if annual_hours_value is None or isinstance(
        annual_hours_value,
        bool,
    ):
        raise EmployeeAnnualHoursMappingError(
            "Paycor annual hours are unavailable"
        )

    try:
        annual_hours = Decimal(str(annual_hours_value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise EmployeeAnnualHoursMappingError(
            "Paycor annual hours are invalid"
        ) from exc

    if not annual_hours.is_finite() or annual_hours <= 0:
        raise EmployeeAnnualHoursMappingError(
            "Paycor annual hours must be greater than zero"
        )

    weekday_hours = int(
        (annual_hours / Decimal("260")).to_integral_value(
            rounding=ROUND_CEILING
        )
    )

    return {
        **{
            field_name: weekday_hours
            for field_name in WEEKDAY_FIXED_WORKING_TIME_FIELDS
        },
        **{
            field_name: 0
            for field_name in WEEKEND_FIXED_WORKING_TIME_FIELDS
        },
    }


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
    """Build Maconomy name1 as 'LastName, FirstName'."""

    first_name = (
        _normalize_optional_string(
            employee_data.get("firstName")
        )
        or ""
    )

    last_name = (
        _normalize_optional_string(
            employee_data.get("lastName")
        )
        or ""
    )

    if last_name and first_name:
        return f"{last_name}, {first_name}"

    return last_name or first_name



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

    # FLSA is optional and comes from Paycor status data.
    status_data = employee_data.get("statusData")

    if isinstance(status_data, dict):
        flsa = _normalize_optional_string(
            status_data.get("flsa")
        )
    else:
        flsa = _normalize_optional_string(
            employee_data.get("flsa")
        )

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

    # Work-location ID and name identify Specification 4.
    work_location_data = employee_data.get(
        "workLocation"
    )

    work_location_id: str | None = None
    work_location_name: str | None = None

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

    # Supports already normalized data.
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

    # Department is completely optional.
    department_id: str | None = None
    department_name: str | None = None
    department_number: str | None = None

    department_reference = employee_data.get(
        "department"
    )

    department_id: str | None = None
    department_name: str | None = None
    department_number: str | None = None

    if isinstance(department_reference, dict):
        department_id = _normalize_optional_string(
            department_reference.get("id")
        )

        # Use a name directly from the employee response,
        # when Paycor provides one.
        department_name = (
            _normalize_optional_string(
                department_reference.get(
                    "description"
                )
            )
            or _normalize_optional_string(
                department_reference.get("name")
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
                    or department_name
                )

                # Keep this only for diagnostics.
                # Do not send it to Maconomy.
                department_number = (
                    _normalize_optional_string(
                        department_data.get("code")
                    )
                )

    # Prefix and suffix come from the matched legal-entity person.
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
        "flsa": flsa,
        "annualHours": employee_data.get("annualHours"),
        "billRateDescription": _normalize_optional_string(
            employee_data.get("billRateDescription")
        ),
        "skillLevel": _normalize_optional_string(
            employee_data.get("skillLevel")
        ),
        "customFieldsError": _normalize_optional_string(
            employee_data.get("customFieldsError")
        ),
        "position": job_title,
        "jobCode": job_code,
        "departmentId": department_id,
        "department": department_name,
        "departmentNumber": department_number,
        "workLocationId": work_location_id,
        "workLocationName": work_location_name,
        "personId": employee_data.get("personId"),
        "primaryAddress": employee_data.get(
            "primaryAddress"
        ),
        "personAddressError": employee_data.get(
            "personAddressError"
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
    require_address: bool = True,
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

    # These are the only values always submitted.
    maconomy_data: dict[str, Any] = {
        "employeenumber": employee_number,

        # Paycor employee UUID remains stored in remark5.
        "remark5": paycor_employee_id,
    }

    maconomy_address = employee_data.get(
        "maconomyAddress"
    )

    if not isinstance(maconomy_address, dict):
        if require_address:
            raise ValueError(
                "Resolved Paycor Primary address is required"
            )
    else:
        maconomy_country = _normalize_optional_string(
            maconomy_address.get("country")
        )

        if maconomy_country is None and require_address:
            raise ValueError(
                "Resolved Maconomy country is required"
            )

        if maconomy_country is not None:
            maconomy_data["country"] = maconomy_country

        for field_name in (
            "name2",
            "name3",
            "postaldistrict",
            "zipcode",
        ):
            value = _normalize_optional_string(
                maconomy_address.get(field_name)
            )

            if value is not None:
                maconomy_data[field_name] = value

        if "name5" in maconomy_address:
            maconomy_data["name5"] = ""

    fixed_working_time = employee_data.get(
        "maconomyFixedWorkingTime"
    )

    if isinstance(fixed_working_time, dict):
        for field_name in FIXED_WORKING_TIME_FIELDS:
            if field_name in fixed_working_time:
                maconomy_data[field_name] = (
                    fixed_working_time[field_name]
                )

    # Optional string fields. Blank values are omitted.
    optional_field_mapping = {
        
        "emailAddress": (
            "electronicmailaddress"
        ),
        "position": "position",
        "maconomySpecification4Name": (
            "specification4name"
        ),
        "prefix": "personaltitle",
        "suffix": "text10",
        "maconomyEmployeeType": "employeetype",
        "billRateDescription": (
            "primaryemployeecategorynumber"
        ),
        "skillLevel": "jobpricegroupnumber",
        "maconomyEntityName": "entityname",
    }
    if include_name_components:
        optional_field_mapping.update(
            {
                "firstName": "firstname",
                "middleName": "middlename",
                "lastName": "lastname",
            }
        )
    
    if not include_name_components:
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
            maconomy_data[maconomy_field] = value

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
    "firstname",
    "middlename",
    "lastname",
    "country",
    "dateemployed",
    "electronicmailaddress",
    "position",
    "entityname",
    "specification4name",
    "personaltitle",
    "text10",
    "employeetype",
    "remark5",
    "superioremployee",
    "name2",
    "name3",
    "name5",
    "postaldistrict",
    "zipcode",
    *FIXED_WORKING_TIME_FIELDS,
)


def map_paycor_employee_to_maconomy_update(
    employee_data: dict[str, Any],
) -> dict[str, Any]:
    """Map only fields currently approved for employee updates."""

    mapped_payload = map_paycor_employee_to_maconomy(
        employee_data,
        include_name_components=True,
        require_address=False,
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
