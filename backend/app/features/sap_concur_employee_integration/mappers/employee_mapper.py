"""Map Maconomy employees to SAP Concur SCIM users and Bulk payloads.

This module is the single source of truth for the Maconomy -> SAP Concur
employee mapping. It is intentionally pure: no HTTP calls, no settings access,
no database access. Only straightforward Maconomy fields are mapped for now.
``spend.customData`` is deliberately not populated; it is a separate list of
custom fields that will be mapped in a later cycle.
"""

from datetime import date, datetime
from typing import Any

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
BULK_REQUEST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:BulkRequest"
ENTERPRISE_USER_SCHEMA = (
    "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
)
SPEND_USER_SCHEMA = "urn:ietf:params:scim:schemas:extension:spend:2.0:User"
SPEND_APPROVER_SCHEMA = (
    "urn:ietf:params:scim:schemas:extension:spend:2.0:Approver"
)
TRAVEL_USER_SCHEMA = "urn:ietf:params:scim:schemas:extension:travel:2.0:User"

# Confirmed tenant profile defaults (WO[#25.9]).
# "Country/Region: United States Of America", "Country Code of Employment: US"
# and "Country of Residence: UNITED STATES" all map to the single SCIM
# `country` field (ISO 3166-1 alpha-2).
DEFAULT_COUNTRY_ISO2 = "US"
DEFAULT_PREFERRED_LANGUAGE = "en-US"  # English (United States)
DEFAULT_LOCALE = "en-US"  # English (United States)
DEFAULT_LEDGER_CODE = "DELTEK"
DEFAULT_REIMBURSEMENT_CURRENCY = "USD"  # "US, Dollar"
DEFAULT_REIMBURSEMENT_TYPE = "Expense Pay By Concur"
DEFAULT_STATE_PROVINCE = ""

DEFAULT_ENTITLEMENTS = ("Expense", "Travel")
DEFAULT_RULE_CLASS_ID = ""
DEFAULT_TRAVEL_GROUP_IDS = ""

# Still pending confirmation (Req[#25] Q-5): omitted while empty.
DEFAULT_COMPANY_ID = ""

BULK_MAX_OPERATIONS = 100
DEFAULT_FAIL_ON_ERRORS = 1

# Maconomy may store a country name instead of an ISO-2 code. Extend this map
# as tenants are confirmed; unknown 2-letter values are passed through.
MACONOMY_COUNTRY_TO_ISO2 = {
    "US": "US",
    "USA": "US",
    "UNITED_STATES_OF_AMERICA": "US",
}


class EmployeeMappingError(ValueError):
    """Raised when a Maconomy employee cannot be mapped to a SCIM user."""

    def __init__(
        self,
        message: str,
        *,
        employee_number: str | None = None,
        bulk_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.employee_number = employee_number
        self.bulk_id = bulk_id


def _clean_str(value: Any) -> str | None:
    """Return a stripped string or None when the value is not usable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _require_email(employee: dict[str, Any]) -> str:
    email = _clean_str(employee.get("electronicmailaddress"))
    if email is None:
        raise EmployeeMappingError(
            "Maconomy electronicmailaddress is required",
            employee_number=_clean_str(employee.get("employeenumber")),
        )
    return email


def _require_employee_number(employee: dict[str, Any]) -> str:
    employee_number = _clean_str(employee.get("employeenumber"))
    if employee_number is None:
        raise EmployeeMappingError(
            "Maconomy employeenumber is required",
            bulk_id=None,
        )
    return employee_number


def _employee_bulk_id(employee: dict[str, Any]) -> str:
    return f"emp-{_require_employee_number(employee)}"


def _is_blocked(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return False


def _phone_digits(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        return None
    digits = "".join(character for character in text if character.isdigit())
    return digits or None


def _format_scim_datetime(value: Any) -> str | None:
    """Format a Maconomy date/datetime as ``YYYY-MM-DDTHH:MM:SS.000``."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(
                text.replace("Z", "+00:00")
            )
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text[:10])
            except ValueError:
                return None
    else:
        return None

    return (
        f"{parsed.year:04d}-{parsed.month:02d}-{parsed.day:02d}"
        f"T{parsed.hour:02d}:{parsed.minute:02d}:{parsed.second:02d}.000"
    )


def _country_iso2(value: Any) -> str | None:
    text = _clean_str(value)
    if text is None:
        return None
    normalized = text.upper().replace(" ", "_").replace("-", "_")
    mapped = MACONOMY_COUNTRY_TO_ISO2.get(normalized)
    if mapped is not None:
        return mapped
    if len(normalized) == 2 and normalized.isalpha():
        return normalized
    return None


def _split_name1(value: Any) -> tuple[str | None, str | None]:
    """Split Maconomy ``name1`` (``"Last, First"``) into (first, last)."""
    text = _clean_str(value)
    if text is None:
        return None, None
    if "," in text:
        last_name, first_name = text.split(",", 1)
        return _clean_str(first_name), _clean_str(last_name)
    return None, text


def _build_name(employee: dict[str, Any]) -> dict[str, str]:
    given_name = _clean_str(employee.get("firstname"))
    family_name = _clean_str(employee.get("lastname"))

    if given_name is None or family_name is None:
        first_from_name1, last_from_name1 = _split_name1(
            employee.get("name1")
        )
        given_name = given_name or first_from_name1
        family_name = family_name or last_from_name1

    name: dict[str, str] = {}
    if given_name is not None:
        name["givenName"] = given_name

    middle_name = _clean_str(employee.get("middlename"))
    if middle_name is not None:
        name["middleName"] = middle_name

    if family_name is not None:
        name["familyName"] = family_name

    return name


def _build_phone_numbers(
    employee: dict[str, Any],
    country_iso2: str | None,
) -> list[dict[str, str]]:
    """Build Home Phone for SCIM User."""
    phone = _phone_digits(employee.get("phone"))
    if phone is None:
        return []

    phone_number = {"type": "home", "value": phone}
    if country_iso2 is not None:
        phone_number["issuingCountry"] = country_iso2
    return [phone_number]


def _build_addresses(
    employee: dict[str, Any],
    country_iso2: str | None,
) -> list[dict[str, str]]:
    """Build Home Address for SCIM User.

    Per client notes, Work Address is automatically populated in SAP Concur
    by selecting Assigned Location (Spec 4) and enabling 'Address same as assigned location'.
    Therefore, the employee's address in Maconomy represents their Home Address.
    """
    address: dict[str, str] = {"type": "home"}

    street_address = _clean_str(
        employee.get("name2")
    ) or _clean_str(employee.get("name3"))
    if street_address is not None:
        address["streetAddress"] = street_address

    locality = _clean_str(employee.get("postaldistrict"))
    if locality is not None:
        address["locality"] = locality

    if DEFAULT_STATE_PROVINCE:
        address["region"] = DEFAULT_STATE_PROVINCE

    postal_code = _clean_str(employee.get("zipcode"))
    if postal_code is not None:
        address["postalCode"] = postal_code

    if country_iso2 is not None:
        address["country"] = country_iso2

    if len(address) == 1:
        return []
    return [address]


def _build_enterprise_extension(
    employee_number: str,
    employee: dict[str, Any],
) -> dict[str, Any]:
    extension: dict[str, Any] = {"employeeNumber": employee_number}

    department = _clean_str(employee.get("entityname"))
    if department is not None:
        extension["department"] = department

    # Spec 4 is Executing office / Assigned Location (e.g., Lakeland, Panama City, Tallahassee, Tampa, Dade City)
    location = _clean_str(employee.get("specification4name"))
    if location is not None:
        extension["location"] = location

    start_date = _format_scim_datetime(employee.get("dateemployed"))
    if start_date is not None:
        extension["startDate"] = start_date

    if DEFAULT_COMPANY_ID:
        extension["companyId"] = DEFAULT_COMPANY_ID

    return extension


def _build_spend_extension(
    country_iso2: str | None,
) -> dict[str, Any]:
    extension: dict[str, Any] = {
        "locale": DEFAULT_LOCALE,
        "ledgerCode": DEFAULT_LEDGER_CODE,
        "reimbursementCurrency": DEFAULT_REIMBURSEMENT_CURRENCY,
    }

    if country_iso2 is not None:
        extension["country"] = country_iso2

    if DEFAULT_STATE_PROVINCE:
        extension["stateProvince"] = DEFAULT_STATE_PROVINCE

    if DEFAULT_REIMBURSEMENT_TYPE:
        extension["reimbursementType"] = DEFAULT_REIMBURSEMENT_TYPE

    # Custom data is intentionally NOT mapped in this cycle (Req FR-20a).
    return extension


def _build_approver_extension(
    employee: dict[str, Any],
) -> dict[str, Any] | None:
    manager = _clean_str(employee.get("superioremployee"))
    if manager is None:
        return None

    return {
        "report": [
            {
                "approver": {"employeeNumber": manager},
                "primary": True,
            }
        ]
    }


def _build_travel_extension(
    employee: dict[str, Any],
) -> dict[str, Any]:
    extension: dict[str, Any] = {
        "ruleClass": {"id": DEFAULT_RULE_CLASS_ID},
        "groups": list(DEFAULT_TRAVEL_GROUP_IDS),
    }

    manager = _clean_str(employee.get("superioremployee"))
    if manager is not None:
        extension["manager"] = {"employeeNumber": manager}

    return extension


def map_maconomy_employee_to_scim_user(
    employee: dict[str, Any],
) -> dict[str, Any]:
    """Map one Maconomy employee dictionary to a SAP Concur SCIM user.

    Only straightforward fields are mapped. ``spend.customData`` is omitted
    and no placeholder custom fields are sent.
    """
    if not isinstance(employee, dict):
        raise EmployeeMappingError(
            "Maconomy employee record must be a dictionary"
        )

    user_name = _require_email(employee)
    employee_number = _require_employee_number(employee)
    country_iso2 = DEFAULT_COUNTRY_ISO2 or _country_iso2(
        employee.get("country")
    )

    user: dict[str, Any] = {
        "schemas": [SCIM_USER_SCHEMA],
        "userName": user_name,
        "active": not _is_blocked(employee.get("blocked")),
        "name": _build_name(employee),
        "preferredLanguage": DEFAULT_PREFERRED_LANGUAGE,
        "emails": [{"type": "work", "value": user_name}],
        "entitlements": list(DEFAULT_ENTITLEMENTS),
        ENTERPRISE_USER_SCHEMA: _build_enterprise_extension(
            employee_number,
            employee,
        ),
        SPEND_USER_SCHEMA: _build_spend_extension(country_iso2),
        TRAVEL_USER_SCHEMA: _build_travel_extension(employee),
    }

    title = _clean_str(employee.get("position"))
    if title is not None:
        user["title"] = title

    phone_numbers = _build_phone_numbers(employee, country_iso2)
    if phone_numbers:
        user["phoneNumbers"] = phone_numbers

    addresses = _build_addresses(employee, country_iso2)
    if addresses:
        user["addresses"] = addresses

    approver_extension = _build_approver_extension(employee)
    if approver_extension is not None:
        user[SPEND_APPROVER_SCHEMA] = approver_extension

    return user


def build_bulk_operations(
    employees: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build one SCIM Bulk operation per mapable employee.

    Returns ``(operations, skipped)``. Unmappable rows are reported in
    ``skipped`` and never abort the remaining employees.
    """
    operations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for employee in employees:
        employee_number = (
            _clean_str(employee.get("employeenumber"))
            if isinstance(employee, dict)
            else None
        )

        try:
            data = map_maconomy_employee_to_scim_user(employee)
            bulk_id = _employee_bulk_id(employee)
        except EmployeeMappingError as exc:
            skipped.append(
                {
                    "employeeNumber": employee_number,
                    "bulkId": (
                        f"emp-{employee_number}"
                        if employee_number is not None
                        else None
                    ),
                    "error": str(exc),
                }
            )
            continue

        operations.append(
            {
                "method": "POST",
                "path": "/Users",
                "bulkId": bulk_id,
                "data": data,
            }
        )

    return operations, skipped


def build_bulk_request(
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the SCIM BulkRequest envelope for one or more operations."""
    if not isinstance(operations, list) or not operations:
        raise EmployeeMappingError(
            "At least one bulk operation is required"
        )

    return {
        "schemas": [BULK_REQUEST_SCHEMA],
        "failOnErrors": DEFAULT_FAIL_ON_ERRORS,
        "Operations": list(operations),
    }
