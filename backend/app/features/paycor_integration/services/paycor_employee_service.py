"""Service for retrieving onboarding employees from Paycor."""

from datetime import date, timedelta
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
        """Return onboarding employees invited today."""

        employees, work_locations = (
            await self._retrieve_onboarding_data()
        )

        return self._filter_employees_by_invited_dates(
            employees=employees,
            work_locations=work_locations,
            valid_dates={date.today()},
        )

    async def get_recent_hires(
        self,
    ) -> list[dict[str, Any]]:
        """Return onboarding employees invited today or yesterday."""

        employees, work_locations = (
            await self._retrieve_onboarding_data()
        )

        today = date.today()
        yesterday = today - timedelta(days=1)

        return self._filter_employees_by_invited_dates(
            employees=employees,
            work_locations=work_locations,
            valid_dates={
                today,
                yesterday,
            },
        )

    async def _retrieve_onboarding_data(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Retrieve onboarding employees and work locations."""

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

                work_locations = (
                    await self._get_all_work_locations(
                        client,
                        access_token,
                    )
                )

                return employees, work_locations

        except httpx.HTTPError as exc:
            raise PaycorServiceError(
                "Unable to retrieve onboarding data "
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

        return await self._get_all_paginated_records(
            client=client,
            access_token=access_token,
            initial_url=initial_url,
            resource_name="employee",
        )

    async def _get_all_work_locations(
        self,
        client: httpx.AsyncClient,
        access_token: str,
    ) -> list[dict[str, Any]]:
        initial_url = (
            f"{self.settings.paycor_url}"
            "/v1/legalentities/"
            f"{self.settings.paycor_legal_entity_id}"
            "/worklocations"
        )

        return await self._get_all_paginated_records(
            client=client,
            access_token=access_token,
            initial_url=initial_url,
            resource_name="work-location",
        )

    async def _get_all_paginated_records(
        self,
        *,
        client: httpx.AsyncClient,
        access_token: str,
        initial_url: str,
        resource_name: str,
    ) -> list[dict[str, Any]]:
        url = initial_url
        params: dict[str, str] | None = None
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
            response.raise_for_status()

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

            if not isinstance(page_records, list) or any(
                not isinstance(record, dict)
                for record in page_records
            ):
                raise PaycorServiceError(
                    f"Invalid Paycor {resource_name} "
                    "response"
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
    ) -> tuple[
        str,
        dict[str, str] | None,
        str,
    ]:
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

            return (
                initial_url,
                {
                    "continuationToken": (
                        normalized_token
                    )
                },
                f"token:{normalized_token}",
            )

        raise PaycorServiceError(
            "Paycor response indicates more results, "
            "but no continuation information was provided"
        )

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

    def _filter_employees_by_invited_dates(
        self,
        *,
        employees: list[dict[str, Any]],
        work_locations: list[dict[str, Any]],
        valid_dates: set[date],
    ) -> list[dict[str, Any]]:
        filtered_employees: list[dict[str, Any]] = []

        for employee in employees:
            invited_date = self._normalize_date(
                employee.get("invitedDate")
            )

            if invited_date not in valid_dates:
                continue

            try:
                filtered_employees.append(
                    map_paycor_employee(
                        employee,
                        work_locations=work_locations,
                    )
                )

            except ValueError as exc:
                raise PaycorServiceError(
                    "Unable to map Paycor employee"
                ) from exc

        return filtered_employees

    @staticmethod
    def _normalize_date(
        value: Any,
    ) -> date | None:
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

    @staticmethod
    def _has_more_results(
        response_data: dict[str, Any],
    ) -> bool:
        value = response_data.get(
            "hasMoreResults"
        )

        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.strip().lower() == "true"

        return False