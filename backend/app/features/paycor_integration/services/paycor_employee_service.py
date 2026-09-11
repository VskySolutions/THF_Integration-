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

        employees, departments = (
            await self._retrieve_employee_data()
        )

        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        return self._filter_employees_by_hire_dates(
            employees=employees,
            departments=departments,
            valid_dates={
                today,
                yesterday,
            },
        )
        
    async def get_employee_by_id(
        self,
        paycor_employee_id: str,
    ) -> dict[str, Any] | None:
        """Return one normalized Paycor employee by employee ID."""

        employees, departments = (
            await self._retrieve_employee_data()
        )

        normalized_employee_id = (
            paycor_employee_id.strip().lower()
        )

        employee = next(
            (
                record
                for record in employees
                if str(
                    record.get("id", "")
                ).strip().lower()
                == normalized_employee_id
            ),
            None,
        )

        if employee is None:
            return None

        departments_by_id = (
            self._build_department_lookup(
                departments
            )
        )

        try:
            return map_paycor_employee(
                employee,
                departments_by_id=departments_by_id,
            )

        except ValueError as exc:
            raise PaycorServiceError(
                "Unable to map Paycor employee "
                f"{paycor_employee_id}"
            ) from exc

    async def get_all_employee_data(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Return all Paycor employees and departments."""

        return await self._retrieve_employee_data()

    async def _retrieve_employee_data(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Retrieve employees and departments from Paycor."""

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                access_token = await self._get_access_token(
                    client
                )

                employees, departments = await asyncio.gather(
                    self._get_all_employees(
                        client,
                        access_token,
                    ),
                    self._get_all_departments(
                        client,
                        access_token,
                    ),
                )

                return employees, departments

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
                f"{self.settings.paycor_url}"
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
            raise PaycorServiceError(
                "Paycor authentication failed with "
                f"HTTP {response.status_code}"
            )

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

    def _filter_employees_by_hire_dates(
        self,
        *,
        employees: list[dict[str, Any]],
        departments: list[dict[str, Any]],
        valid_dates: set[date],
    ) -> list[dict[str, Any]]:
        """Filter and map employees using their hire dates."""

        filtered_employees: list[dict[str, Any]] = []

        departments_by_id = (
            self._build_department_lookup(
                departments
            )
        )

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
                employment_date_data.get(
                    "hireDate"
                )
            )

            if hire_date not in valid_dates:
                continue

            try:
                mapped_employee = map_paycor_employee(
                    employee,
                    departments_by_id=(
                        departments_by_id
                    ),
                )

            except ValueError as exc:
                employee_id = employee.get("id")

                raise PaycorServiceError(
                    "Unable to map Paycor employee "
                    f"{employee_id}"
                ) from exc

            filtered_employees.append(
                mapped_employee
            )

        return filtered_employees

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