"""Service for retrieving employees from Paycor."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import Settings, get_settings
from app.features.paycor_integration.mappers import (
    map_paycor_employee,
)



class PaycorServiceError(Exception):
    """Raised when Paycor employee data cannot be retrieved."""


class PaycorService:
    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0
        self.max_pages = 1000

    async def get_recent_hires(
        self,
    ) -> list[dict[str, Any]]:
        """Return active Paycor employees hired today or yesterday."""

        (
            employees,
            departments,
            person_details_by_id,
            annual_hours_by_employee_id,
        ) = (
            await self._retrieve_employee_data()
        )

        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        recent_employees: list[dict[str, Any]] = []

        for employee in employees:
            employment_date_data = employee.get(
                "employmentDateData"
            )

            if not isinstance(
                employment_date_data,
                dict,
            ):
                continue

            hire_date = self._normalize_date(
                employment_date_data.get("hireDate")
            )

            if hire_date in {
                today,
                yesterday,
            }:
                recent_employees.append(employee)

        return await self._map_employee_records(
                employees=recent_employees,
                departments=departments,
                person_details_by_id=(
                    person_details_by_id
                ),
                annual_hours_by_employee_id=(
                    annual_hours_by_employee_id
                ),
        )
        
    async def get_employee_by_number(
        self,
        paycor_employee_number: str,
    ) -> dict[str, Any] | None:
        """Return one normalized Paycor employee by employee number."""

        (
            employees,
            departments,
            person_details_by_id,
            annual_hours_by_employee_id,
        ) = (
            await self._retrieve_employee_data()
        )

        normalized_employee_number = (
            paycor_employee_number.strip()
        )

        matching_employees = [
            record
            for record in employees
            if str(
                record.get("employeeNumber", "")
            ).strip()
            == normalized_employee_number
        ]

        if not matching_employees:
            return None

        if len(matching_employees) > 1:
            raise PaycorServiceError(
                "Multiple Paycor employees have employee number "
                f"{normalized_employee_number!r}"
            )

        mapped_employees = await (
            self._map_employee_records(
                employees=[matching_employees[0]],
                departments=departments,
                person_details_by_id=(
                    person_details_by_id
                ),
                annual_hours_by_employee_id=(
                    annual_hours_by_employee_id
                ),
            )
        )

        return mapped_employees[0]

    async def get_all_employee_data(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, Any],
    ]:
        """Return employees, departments, and person details."""

        return await self._retrieve_employee_data()
    
    async def _map_employee_records(
        self,
        *,
        employees: list[dict[str, Any]],
        departments: list[dict[str, Any]],
        person_details_by_id: dict[
            str,
            dict[str, Any],
        ],
        annual_hours_by_employee_id: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Enrich and map Paycor employee records."""

        departments_by_id = (
            self._build_department_lookup(
                departments
            )
        )

        mapped_employees: list[dict[str, Any]] = []

        for employee in employees:
            employee_id = str(employee.get("id"))
            enriched_employee = self.enrich_employee_with_person(
                employee,
                person_details_by_id=person_details_by_id,
            )
            enriched_employee = (
                self.enrich_employee_with_annual_hours(
                    enriched_employee,
                    annual_hours_by_employee_id=(
                        annual_hours_by_employee_id
                    ),
                )
            )

            try:
                mapped_employee = map_paycor_employee(
                    enriched_employee,
                    departments_by_id=(
                        departments_by_id
                    ),
                )

            except ValueError as exc:
                raise PaycorServiceError(
                    "Unable to map Paycor employee "
                    f"{employee_id}: {exc}"
                ) from exc

            mapped_employees.append(
                mapped_employee
            )

        return mapped_employees

    async def _retrieve_employee_data(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, Any],
    ]:
        """Retrieve employees, departments, and persons from Paycor."""

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                access_token = await self._get_access_token(
                    client
                )

                (
                    employees,
                    departments,
                    persons,
                    pay_rates,
                ) = await asyncio.gather(
                    self._get_all_employees(
                        client,
                        access_token,
                    ),
                    self._get_all_departments(
                        client,
                        access_token,
                    ),
                    self._get_all_persons(
                        client,
                        access_token,
                    ),
                    self._get_all_pay_rates(
                        client,
                        access_token,
                    ),
                )

                return (
                    employees,
                    departments,
                    self._build_person_details_lookup(
                        persons
                    ),
                    self._build_annual_hours_lookup(
                        pay_rates
                    ),
                )

        except PaycorServiceError:
            raise

        except httpx.HTTPError as exc:
            raise PaycorServiceError(
                "Unable to retrieve employee data "
                "from Paycor"
            ) from exc

    async def _get_access_token(
        self,
        client: httpx.AsyncClient,
    ) -> str:
        response = await client.post(
            (
                f"{self.settings.paycor_url.rstrip('/')}"
                "/sts/v1/common/token"
            ),
            params={
                "subscription-key": (
                    self.settings
                    .paycor_subscription_key
                    .get_secret_value()
                )
            },
            headers={
                "Accept": "application/json",
                "Content-Type": (
                    "application/x-www-form-urlencoded"
                ),
            },
            data={
                "grant_type": "refresh_token",
                "client_id": (
                    self.settings.paycor_client_id
                    .get_secret_value()
                ),
                "client_secret": (
                    self.settings
                    .paycor_client_secret
                    .get_secret_value()
                ),
                "refresh_token": (
                    self.settings
                    .paycor_refresh_token
                    .get_secret_value()
                ),
            },
        )

        if response.is_error:
            response_body = response.text.strip()

            message = (
                "Paycor authentication failed with "
                f"HTTP {response.status_code}"
            )

            if response_body:
                message = (
                    f"{message}: "
                    f"{response_body[:2000]}"
                )

            raise PaycorServiceError(message)

        try:
            response_data = response.json()
            access_token = response_data["access_token"]

        except (KeyError, TypeError, ValueError) as exc:
            raise PaycorServiceError(
                "Invalid Paycor authentication response"
            ) from exc

        if (
            not isinstance(access_token, str)
            or not access_token.strip()
        ):
            raise PaycorServiceError(
                "Invalid Paycor authentication response"
            )

        return access_token.strip()

    def _get_api_headers(
        self,
        access_token: str,
    ) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": (
                f"Bearer {access_token}"
            ),
            "Ocp-Apim-Subscription-Key": (
                self.settings
                .paycor_subscription_key
                .get_secret_value()
            ),
        }

    async def _get_all_employees(
        self,
        client: httpx.AsyncClient,
        access_token: str,
    ) -> list[dict[str, Any]]:
        """Retrieve all active employees for the legal entity."""

        initial_url = (
            f"{self.settings.paycor_url}"
            "/v1/legalentities/"
            f"{self.settings.paycor_legal_entity_id}"
            "/employees"
        )

        initial_params = [
            ("include", "EmploymentDates"),
            ("include", "Status"),
            ("include", "Position"),
            ("include", "WorkLocation"),
            ("emailType", "Work"),
            ("statusFilter", "Active"),
        ]

        return await self._get_all_paginated_records(
            client=client,
            access_token=access_token,
            initial_url=initial_url,
            initial_params=initial_params,
            resource_name="employee",
        )

    async def _get_all_departments(
        self,
        client: httpx.AsyncClient,
        access_token: str,
    ) -> list[dict[str, Any]]:
        """Retrieve all departments for the legal entity."""

        initial_url = (
            f"{self.settings.paycor_url}"
            "/v1/legalentities/"
            f"{self.settings.paycor_legal_entity_id}"
            "/departments"
        )

        return await self._get_all_paginated_records(
            client=client,
            access_token=access_token,
            initial_url=initial_url,
            initial_params=None,
            resource_name="department",
        )

    async def _get_all_persons(
        self,
        client: httpx.AsyncClient,
        access_token: str,
    ) -> list[dict[str, Any]]:
        """Retrieve all persons and addresses for the legal entity."""

        initial_url = (
            f"{self.settings.paycor_url.rstrip('/')}"
            "/v1/legalEntities/"
            f"{self.settings.paycor_legal_entity_id}"
            "/persons"
        )

        return await self._get_all_paginated_records(
            client=client,
            access_token=access_token,
            initial_url=initial_url,
            initial_params=[
                ("include", "Addresses"),
                (
                    "includeUnpaidWorkersDetails",
                    "false",
                ),
            ],
            resource_name="person",
        )

    async def _get_all_pay_rates(
        self,
        client: httpx.AsyncClient,
        access_token: str,
    ) -> list[dict[str, Any]]:
        """Retrieve all pay rates for the legal entity."""

        initial_url = (
            f"{self.settings.paycor_url.rstrip('/')}"
            "/v1/legalentities/"
            f"{self.settings.paycor_legal_entity_id}"
            "/payrates"
        )

        return await self._get_all_paginated_records(
            client=client,
            access_token=access_token,
            initial_url=initial_url,
            initial_params=None,
            resource_name="pay rate",
        )

    @classmethod
    def _build_annual_hours_lookup(
        cls,
        pay_rates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Select the latest currently effective rate per employee."""

        today = datetime.now(timezone.utc).date()
        candidates: dict[
            str,
            list[tuple[date, int, Any]],
        ] = {}

        for pay_rate in pay_rates:
            employee_reference = pay_rate.get("employee")
            employee_id = (
                cls._normalize_person_id(
                    employee_reference.get("id")
                )
                if isinstance(employee_reference, dict)
                else None
            )

            if employee_id is None:
                continue

            effective_start = cls._normalize_date(
                pay_rate.get("effectiveStartDate")
            )
            effective_end = cls._normalize_date(
                pay_rate.get("effectiveEndDate")
            )

            if effective_start is None or effective_start > today:
                continue

            if effective_end is not None and effective_end < today:
                continue

            try:
                sequence_number = int(
                    pay_rate.get("sequenceNumber") or 0
                )
            except (TypeError, ValueError):
                sequence_number = 0

            candidates.setdefault(employee_id, []).append(
                (
                    effective_start,
                    sequence_number,
                    pay_rate.get("annualHours"),
                )
            )

        return {
            employee_id: max(
                employee_candidates,
                key=lambda candidate: (
                    candidate[0],
                    candidate[1],
                ),
            )[2]
            for employee_id, employee_candidates
            in candidates.items()
        }

    @classmethod
    def _build_person_details_lookup(
        cls,
        persons: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Index each person and their single Primary address by ID."""

        lookup: dict[str, dict[str, Any]] = {}

        for person in persons:
            person_id = cls._normalize_person_id(
                person.get("id")
            )

            if person_id is None:
                raise PaycorServiceError(
                    "Paycor person record is missing its ID"
                )

            if person_id in lookup:
                raise PaycorServiceError(
                    "Paycor returned duplicate person ID "
                    f"{person_id}"
                )

            addresses = person.get("addresses")

            if addresses is None:
                addresses = []

            if not isinstance(addresses, list) or any(
                not isinstance(address, dict)
                for address in addresses
            ):
                lookup[person_id] = {
                    "prefix": person.get("prefix"),
                    "suffix": person.get("suffix"),
                    "primaryAddress": None,
                    "_error": (
                        "Invalid Paycor person addresses for "
                        f"person {person_id}"
                    ),
                }
                continue

            primary_addresses = [
                address
                for address in addresses
                if str(address.get("type") or "")
                .strip()
                .casefold()
                == "primary"
            ]

            person_error: str | None = None

            if len(primary_addresses) > 1:
                person_error = (
                    "Paycor returned multiple Primary addresses "
                    f"for person {person_id}"
                )

            lookup[person_id] = {
                "prefix": person.get("prefix"),
                "suffix": person.get("suffix"),
                "primaryAddress": (
                    primary_addresses[0]
                    if len(primary_addresses) == 1
                    else None
                ),
                "_error": person_error,
            }

        return lookup

    @classmethod
    def enrich_employee_with_person(
        cls,
        employee: dict[str, Any],
        *,
        person_details_by_id: dict[
            str,
            dict[str, Any],
        ],
    ) -> dict[str, Any]:
        """Match an employee to a person strictly through person.id."""

        person_reference = employee.get("person")
        person_id = (
            cls._normalize_person_id(
                person_reference.get("id")
            )
            if isinstance(person_reference, dict)
            else None
        )

        if person_id is None:
            return {
                **employee,
                "personId": None,
                "primaryAddress": None,
                "personAddressError": (
                    "Paycor employee person ID is required "
                    "for address mapping"
                ),
            }

        person_details = person_details_by_id.get(
            person_id
        )

        if person_details is None:
            return {
                **employee,
                "personId": person_id,
                "primaryAddress": None,
                "personAddressError": (
                    "No Paycor person record matches employee "
                    f"person ID {person_id}"
                ),
            }

        return {
            **employee,
            "personId": person_id,
            "primaryAddress": person_details.get(
                "primaryAddress"
            ),
            "personAddressError": person_details.get(
                "_error"
            ),
            "prefix": person_details.get("prefix"),
            "suffix": person_details.get("suffix"),
        }

    @classmethod
    def enrich_employee_with_annual_hours(
        cls,
        employee: dict[str, Any],
        *,
        annual_hours_by_employee_id: dict[str, Any],
    ) -> dict[str, Any]:
        """Attach annual hours by matching the Paycor employee ID."""

        employee_id = cls._normalize_person_id(
            employee.get("id")
            or employee.get("paycorEmployeeId")
        )

        return {
            **employee,
            "annualHours": (
                annual_hours_by_employee_id.get(employee_id)
                if employee_id is not None
                else None
            ),
        }

    @staticmethod
    def _normalize_person_id(value: Any) -> str | None:
        if value is None:
            return None

        normalized_value = str(value).strip()
        return normalized_value.casefold() or None

    async def _get_all_paginated_records(
        self,
        *,
        client: httpx.AsyncClient,
        access_token: str,
        initial_url: str,
        initial_params: list[
            tuple[str, str]
        ] | None,
        resource_name: str,
    ) -> list[dict[str, Any]]:
        """Retrieve all pages from a Paycor list endpoint."""

        url = initial_url

        params = (
            list(initial_params)
            if initial_params
            else None
        )

        records: list[dict[str, Any]] = []
        seen_cursors: set[str] = set()

        headers = self._get_api_headers(
            access_token
        )

        for _ in range(self.max_pages):
            response = await client.get(
                url,
                headers=headers,
                params=params,
            )

            try:
                response.raise_for_status()

            except httpx.HTTPStatusError as exc:
                response_text = (
                    exc.response.text.strip()
                )

                raise PaycorServiceError(
                    f"Paycor {resource_name} request "
                    "failed with HTTP "
                    f"{exc.response.status_code}: "
                    f"{response_text[:1000]}"
                ) from exc

            try:
                response_data = response.json()

            except (TypeError, ValueError) as exc:
                raise PaycorServiceError(
                    f"Invalid Paycor {resource_name} "
                    "response"
                ) from exc

            if not isinstance(response_data, dict):
                raise PaycorServiceError(
                    f"Invalid Paycor {resource_name} "
                    "response"
                )

            page_records = response_data.get(
                "records"
            )

            if not isinstance(page_records, list):
                raise PaycorServiceError(
                    f"Invalid Paycor {resource_name} "
                    "response"
                )

            if any(
                not isinstance(record, dict)
                for record in page_records
            ):
                raise PaycorServiceError(
                    f"Invalid Paycor {resource_name} "
                    "record"
                )

            records.extend(page_records)

            if not self._has_more_results(
                response_data
            ):
                return records

            url, params, cursor = (
                self._get_next_page_request(
                    response_data=response_data,
                    initial_url=initial_url,
                    initial_params=initial_params,
                )
            )

            if cursor in seen_cursors:
                raise PaycorServiceError(
                    f"Paycor {resource_name} pagination "
                    "returned a repeated cursor"
                )

            seen_cursors.add(cursor)

        raise PaycorServiceError(
            f"Paycor {resource_name} pagination "
            "exceeded the maximum page limit"
        )

    def _get_next_page_request(
        self,
        *,
        response_data: dict[str, Any],
        initial_url: str,
        initial_params: list[tuple[str, str]] | None,
    ) -> tuple[
        str,
        list[tuple[str, str]] | None,
        str,
    ]:
        """Build the request for the next Paycor page."""

        additional_results_url = response_data.get(
            "additionalResultsUrl"
        )
        continuation_token = response_data.get(
            "continuationToken"
        )

        if (
            isinstance(additional_results_url, str)
            and additional_results_url.strip()
        ):
            normalized_url = (
                additional_results_url.strip()
            )

            next_url = urljoin(
                f"{self.settings.paycor_url.rstrip('/')}/",
                normalized_url,
            )

            return (
                next_url,
                None,
                f"url:{normalized_url}",
            )

        if (
            isinstance(continuation_token, str)
            and continuation_token.strip()
        ):
            normalized_token = (
                continuation_token.strip()
            )

            next_params = list(initial_params or [])
            next_params.append(
                (
                    "continuationToken",
                    normalized_token,
                )
            )

            return (
                initial_url,
                next_params,
                f"token:{normalized_token}",
            )

        raise PaycorServiceError(
            "Paycor response indicates more results, "
            "but no continuation information was provided"
        )

    @staticmethod
    def _has_more_results(
        response_data: dict[str, Any],
    ) -> bool:
        """Return whether Paycor indicates another page exists."""

        value = response_data.get(
            "hasMoreResults"
        )

        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.strip().lower() == "true"

        return False

    

    @staticmethod
    def _build_department_lookup(
        departments: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Build a department lookup using Paycor department ID."""

        departments_by_id: dict[
            str,
            dict[str, Any],
        ] = {}

        for department in departments:
            department_id = department.get("id")

            if (
                isinstance(department_id, str)
                and department_id.strip()
            ):
                departments_by_id[
                    department_id.strip()
                ] = department

        return departments_by_id

    @staticmethod
    def _normalize_date(
        value: Any,
    ) -> date | None:
        """Convert a Paycor datetime string into a date."""

        if not isinstance(value, str):
            return None

        normalized_value = value.strip()

        if not normalized_value:
            return None

        try:
            return date.fromisoformat(
                normalized_value[:10]
            )

        except ValueError:
            return None
        
        
    
