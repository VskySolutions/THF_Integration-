"""Service for retrieving onboarding employees from Paycor."""

from datetime import date
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import Settings, get_settings
from app.features.paycor_integration.mappers import (
    map_paycor_employee,
)


class PaycorServiceError(Exception):
    pass


class PaycorService:
    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0
        self.max_pages = 1000

    async def get_hired_employees_today(
        self,
    ) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                access_token = await self._get_access_token(
                    client
                )

                employees = (
                    await self._get_all_onboarding_employees(
                        client,
                        access_token,
                    )
                )

        except httpx.HTTPError as exc:
            raise PaycorServiceError(
                "Unable to retrieve employees from Paycor"
            ) from exc

        today = date.today()

        try:
            return [
                map_paycor_employee(employee)
                for employee in employees
                if (
                    self._is_hired_on(employee, today)
                    and employee.get("employeeNumber")
                    is not None
                )
            ]

        except ValueError as exc:
            raise PaycorServiceError(str(exc)) from exc

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

        return access_token

    async def _get_all_onboarding_employees(
        self,
        client: httpx.AsyncClient,
        access_token: str,
    ) -> list[dict[str, Any]]:
        initial_url = (
            f"{self.settings.paycor_url}"
            "/v2/legalentities/"
            f"{self.settings.paycor_legal_entity_id}"
            "/onboardingemployees"
        )

        url = initial_url
        params: dict[str, str] | None = None
        employees: list[dict[str, Any]] = []
        seen_cursors: set[str] = set()

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Ocp-Apim-Subscription-Key": (
                self.settings
                .paycor_subscription_key
                .get_secret_value()
            ),
        }

        for _ in range(self.max_pages):
            response = await client.get(
                url,
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            try:
                response_data = response.json()

            except (TypeError, ValueError) as exc:
                raise PaycorServiceError(
                    "Invalid Paycor employee response"
                ) from exc

            if not isinstance(response_data, dict):
                raise PaycorServiceError(
                    "Invalid Paycor employee response"
                )

            records = response_data.get("records")

            if not isinstance(records, list) or any(
                not isinstance(record, dict)
                for record in records
            ):
                raise PaycorServiceError(
                    "Invalid Paycor employee response"
                )

            employees.extend(records)

            if not self._as_bool(
                response_data.get("hasMoreResults")
            ):
                return employees

            additional_results_url = str(
                response_data.get(
                    "additionalResultsUrl"
                )
                or ""
            ).strip()

            continuation_token = str(
                response_data.get(
                    "continuationToken"
                )
                or ""
            ).strip()

            if additional_results_url:
                cursor = (
                    f"url:{additional_results_url}"
                )

                url = urljoin(
                    f"{self.settings.paycor_url}/",
                    additional_results_url,
                )

                params = None

            elif continuation_token:
                cursor = (
                    f"token:{continuation_token}"
                )

                url = initial_url

                params = {
                    "continuationToken": (
                        continuation_token
                    )
                }

            else:
                raise PaycorServiceError(
                    "Paycor returned hasMoreResults=true "
                    "without a pagination cursor"
                )

            if cursor in seen_cursors:
                raise PaycorServiceError(
                    "Paycor returned a repeated "
                    "pagination cursor"
                )

            seen_cursors.add(cursor)

        raise PaycorServiceError(
            "Paycor pagination limit exceeded"
        )

    @staticmethod
    def _is_hired_on(
        employee: dict[str, Any],
        expected_date: date,
    ) -> bool:
        hire_date = employee.get("hireDate")

        if not hire_date:
            return False

        try:
            parsed_date = date.fromisoformat(
                str(hire_date)[:10]
            )

        except ValueError:
            return False

        return parsed_date == expected_date

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.strip().lower() == "true"

        return bool(value)