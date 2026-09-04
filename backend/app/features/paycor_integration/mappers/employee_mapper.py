from datetime import date
from typing import Any

from app.features.paycor_integration.constants import (
    EmployeeStatus,
)


# Add other countries only after confirmation.
PAYCOR_TO_MACONOMY_COUNTRY = {
    "USA": "united_states_of_america",
}


def _normalize_optional_date(
    value: Any,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError(
            f"Paycor {field_name} must be a string or null"
        )

    return value.strip() or None


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


def get_country_by_work_location_id(
    work_location_id: Any,
    work_locations: list[dict[str, Any]],
) -> str | None:
    if (
        not isinstance(work_location_id, str)
        or not work_location_id.strip()
    ):
        return None

    normalized_location_id = (
        work_location_id.strip()
    )

    for work_location in work_locations:
        location_id = work_location.get("id")

        if (
            not isinstance(location_id, str)
            or location_id.strip()
            != normalized_location_id
        ):
            continue

        addresses = work_location.get("addresses")

        if not isinstance(addresses, list):
            return None

        countries: set[str] = set()

        for address in addresses:
            if not isinstance(address, dict):
                continue

            country = address.get("country")

            if (
                isinstance(country, str)
                and country.strip()
            ):
                countries.add(
                    country.strip().upper()
                )

        if len(countries) == 1:
            return next(iter(countries))

        return None

    return None


def map_paycor_employee(
    employee_data: dict[str, Any],
    *,
    work_locations: list[dict[str, Any]],
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
    work_location_id = employee_data.get(
        "workLocationId"
    )

    hire_date = _normalize_optional_date(
        employee_data.get("hireDate"),
        "hireDate",
    )
    invited_date = _normalize_optional_date(
        employee_data.get("invitedDate"),
        "invitedDate",
    )

    if (
        not isinstance(onboarding_employee_id, str)
        or not onboarding_employee_id.strip()
    ):
        raise ValueError(
            "Paycor onboarding employee ID is required"
        )

    if (
        not isinstance(legal_entity_id, int)
        or isinstance(legal_entity_id, bool)
    ):
        raise ValueError(
            "Paycor legal entity ID must be an integer"
        )

    parsed_hire_date = (
        _parse_paycor_date(
            hire_date,
            "hireDate",
        )
        if hire_date is not None
        else None
    )

    employee_status = (
        EmployeeStatus.HIRED.value
        if (
            parsed_hire_date is not None
            and parsed_hire_date <= date.today()
        )
        else EmployeeStatus.INVITED.value
    )

    work_location_country = (
        get_country_by_work_location_id(
            work_location_id,
            work_locations,
        )
    )

    return {
        "onboardingEmployeeId": (
            onboarding_employee_id.strip()
        ),
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
        "invitedDate": invited_date,
        "hireDate": hire_date,
        "employeeStatus": employee_status,
        "workLocation": employee_data.get(
            "workLocation"
        ),
        "workLocationId": work_location_id,
        "workLocationCountry": (
            work_location_country
        ),
        "manager": employee_data.get(
            "manager"
        ),
        "managerId": employee_data.get(
            "managerId"
        ),
    }


def map_paycor_employee_to_maconomy(
    employee_data: dict[str, Any],
) -> dict[str, Any]:
    full_name = employee_data.get(
        "fullName"
    )
    invited_date = employee_data.get(
        "invitedDate"
    )
    email_address = employee_data.get(
        "emailAddress"
    )
    work_location_country = employee_data.get(
        "workLocationCountry"
    )

    if (
        not isinstance(full_name, str)
        or not full_name.strip()
    ):
        raise ValueError(
            "Paycor employee full name is required"
        )

    if (
        not isinstance(invited_date, str)
        or not invited_date.strip()
    ):
        raise ValueError(
            "Paycor invited date is required"
        )

    if (
        not isinstance(work_location_country, str)
        or not work_location_country.strip()
    ):
        raise ValueError(
            "Paycor work-location country is required"
        )

    date_employed = _parse_paycor_date(
        invited_date,
        "invitedDate",
    )

    paycor_country = (
        work_location_country.strip().upper()
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

    maconomy_data: dict[str, Any] = {
        "name1": full_name.strip(),
        "dateemployed": date_employed.isoformat(),
        "country": maconomy_country,
    }

    if (
        isinstance(email_address, str)
        and email_address.strip()
    ):
        maconomy_data[
            "electronicmailaddress"
        ] = email_address.strip()

    return maconomy_data