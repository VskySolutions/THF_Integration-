"""Service for writing timesheet data to Paycor."""

from typing import Any
from urllib.parse import urljoin

import httpx


from app.core.config import Settings, get_settings


class PaycorTimesheetServiceError(Exception):
    """Raised when Paycor timesheet processing fails."""


class PaycorTimesheetService:
    """Retrieve Paycor references and submit employee hours."""

    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0
        self.max_pages = 1000

    async def get_earning_codes(
        self,
    ) -> dict[str, str]:
        """Return canonical Paycor earning codes."""

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                access_token = (
                    await self._get_access_token(
                        client
                    )
                )

                earning_records = (
                    await self._get_all_earnings(
                        client=client,
                        access_token=access_token,
                    )
                )

        except PaycorTimesheetServiceError:
            raise

        except httpx.HTTPError as exc:
            raise PaycorTimesheetServiceError(
                "Unable to retrieve earnings "
                "from Paycor"
            ) from exc

        return self._build_earning_code_lookup(
            earning_records
        )

    async def get_department_codes_by_name(
        self,
    ) -> dict[str, str]:
        """Return Paycor department codes indexed by name."""

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                access_token = (
                    await self._get_access_token(
                        client
                    )
                )

                department_records = (
                    await self._get_all_departments(
                        client=client,
                        access_token=access_token,
                    )
                )

        except PaycorTimesheetServiceError:
            raise

        except httpx.HTTPError as exc:
            raise PaycorTimesheetServiceError(
                "Unable to retrieve departments "
                "from Paycor"
            ) from exc

        return self._build_department_code_lookup(
            department_records
        )

    async def get_timesheet_reference_data(
        self,
    ) -> tuple[
        dict[str, str],
        dict[str, str],
    ]:
        """Retrieve earnings and departments for mapping."""

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                access_token = (
                    await self._get_access_token(
                        client
                    )
                )

                earning_records = (
                    await self._get_all_earnings(
                        client=client,
                        access_token=access_token,
                    )
                )

                department_records = (
                    await self._get_all_departments(
                        client=client,
                        access_token=access_token,
                    )
                )

        except PaycorTimesheetServiceError:
            raise

        except httpx.HTTPError as exc:
            raise PaycorTimesheetServiceError(
                "Unable to retrieve Paycor "
                "timesheet reference data"
            ) from exc

        return (
            self._build_earning_code_lookup(
                earning_records
            ),
            self._build_department_code_lookup(
                department_records
            ),
        )


    async def submit_payroll_hours(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit payroll hours to Paycor Paygrid."""

        url = (
            f"{self.settings.paycor_url.rstrip('/')}"
            "/v1/legalentities/"
            f"{self.settings.paycor_legal_entity_id}"
            "/payrollhours"
        )

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                access_token = (
                    await self._get_access_token(
                        client
                    )
                )

                response = await client.post(
                    url,
                    headers=self._get_api_headers(
                        access_token
                    ),
                    json=payload,
                )

        except httpx.RequestError as exc:
            raise PaycorTimesheetServiceError(
                "Unable to connect to Paycor "
                "while submitting payroll hours"
            ) from exc

        if response.is_error:
            response_body = response.text.strip()

            message = (
                "Paycor payroll-hours request failed "
                f"with HTTP {response.status_code}"
            )

            if response_body:
                message = (
                    f"{message}: "
                    f"{response_body[:2000]}"
                )

            raise PaycorTimesheetServiceError(
                message
            )

        response_data: Any = None

        if response.content:
            try:
                response_data = response.json()
            except ValueError:
                response_data = response.text

        return {
            "status": (
                "ACCEPTED"
                if response.status_code == 202
                else "SUCCESS"
            ),
            "httpStatus": response.status_code,
            "processId": payload.get("processId"),
            "paycorResponse": response_data,
        }
    
    async def _get_access_token(
        self,
        client: httpx.AsyncClient,
    ) -> str:
        """Retrieve a Paycor access token."""

        token_url = (
            f"{self.settings.paycor_url.rstrip('/')}"
            "/sts/v1/common/token"
        )

        response = await client.post(
            token_url,
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
                    self.settings
                    .paycor_client_id
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
                "Paycor authentication failed "
                f"with HTTP {response.status_code}"
            )

            if response_body:
                message = (
                    f"{message}: "
                    f"{response_body[:2000]}"
                )

            raise PaycorTimesheetServiceError(
                message
            )

        try:
            response_data = response.json()
            access_token = response_data[
                "access_token"
            ]

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise PaycorTimesheetServiceError(
                "Invalid Paycor authentication "
                "response"
            ) from exc

        if (
            not isinstance(access_token, str)
            or not access_token.strip()
        ):
            raise PaycorTimesheetServiceError(
                "Invalid Paycor authentication "
                "response"
            )

        return access_token.strip()

    def _get_api_headers(
        self,
        access_token: str,
    ) -> dict[str, str]:
        """Build headers required by Paycor APIs."""

        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": (
                f"Bearer {access_token}"
            ),
            "Ocp-Apim-Subscription-Key": (
                self.settings
                .paycor_subscription_key
                .get_secret_value()
            ),
        }

    async def _get_all_earnings(
        self,
        *,
        client: httpx.AsyncClient,
        access_token: str,
    ) -> list[dict[str, Any]]:
        """Retrieve all legal-entity earnings."""

        initial_url = (
            f"{self.settings.paycor_url.rstrip('/')}"
            "/v1/legalentities/"
            f"{self.settings.paycor_legal_entity_id}"
            "/earnings"
        )

        return await self._get_all_paginated_records(
            client=client,
            access_token=access_token,
            initial_url=initial_url,
            initial_params=None,
            resource_name="earnings",
        )

    async def _get_all_departments(
        self,
        *,
        client: httpx.AsyncClient,
        access_token: str,
    ) -> list[dict[str, Any]]:
        """Retrieve all Paycor legal-entity departments."""

        initial_url = (
            f"{self.settings.paycor_url.rstrip('/')}"
            "/v1/legalentities/"
            f"{self.settings.paycor_legal_entity_id}"
            "/departments"
        )

        return await self._get_all_paginated_records(
            client=client,
            access_token=access_token,
            initial_url=initial_url,
            initial_params=None,
            resource_name="departments",
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
                response_body = (
                    exc.response.text.strip()
                )

                message = (
                    f"Paycor {resource_name} request "
                    "failed with HTTP "
                    f"{exc.response.status_code}"
                )

                if response_body:
                    message = (
                        f"{message}: "
                        f"{response_body[:2000]}"
                    )

                raise PaycorTimesheetServiceError(
                    message
                ) from exc

            try:
                response_data = response.json()

            except (TypeError, ValueError) as exc:
                raise PaycorTimesheetServiceError(
                    f"Invalid Paycor {resource_name} "
                    "response"
                ) from exc

            if not isinstance(
                response_data,
                dict,
            ):
                raise PaycorTimesheetServiceError(
                    f"Invalid Paycor {resource_name} "
                    "response"
                )

            page_records = response_data.get(
                "records"
            )

            if not isinstance(
                page_records,
                list,
            ):
                raise PaycorTimesheetServiceError(
                    f"Invalid Paycor {resource_name} "
                    "response"
                )

            if any(
                not isinstance(record, dict)
                for record in page_records
            ):
                raise PaycorTimesheetServiceError(
                    f"Invalid Paycor {resource_name} "
                    "record"
                )

            records.extend(page_records)

            if not self._has_more_results(
                response_data
            ):
                return records

            (
                url,
                params,
                cursor,
            ) = self._get_next_page_request(
                response_data=response_data,
                initial_url=initial_url,
                initial_params=initial_params,
            )

            if cursor in seen_cursors:
                raise PaycorTimesheetServiceError(
                    f"Paycor {resource_name} pagination "
                    "returned a repeated cursor"
                )

            seen_cursors.add(cursor)

        raise PaycorTimesheetServiceError(
            f"Paycor {resource_name} pagination "
            "exceeded the maximum page limit"
        )

    def _get_next_page_request(
        self,
        *,
        response_data: dict[str, Any],
        initial_url: str,
        initial_params: list[
            tuple[str, str]
        ] | None,
    ) -> tuple[
        str,
        list[tuple[str, str]] | None,
        str,
    ]:
        """Build the request for the next Paycor page."""

        additional_results_url = (
            response_data.get(
                "additionalResultsUrl"
            )
        )

        continuation_token = (
            response_data.get(
                "continuationToken"
            )
        )

        if (
            isinstance(
                additional_results_url,
                str,
            )
            and additional_results_url.strip()
        ):
            normalized_url = (
                additional_results_url.strip()
            )

            next_url = urljoin(
                (
                    f"{self.settings.paycor_url.rstrip('/')}/"
                ),
                normalized_url,
            )

            return (
                next_url,
                None,
                f"url:{normalized_url}",
            )

        if (
            isinstance(
                continuation_token,
                str,
            )
            and continuation_token.strip()
        ):
            normalized_token = (
                continuation_token.strip()
            )

            next_params = list(
                initial_params or []
            )
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

        raise PaycorTimesheetServiceError(
            "Paycor response indicates more results, "
            "but no continuation information was provided"
        )

    
    
    @staticmethod
    def _has_more_results(
        response_data: dict[str, Any],
    ) -> bool:
        """Return whether another Paycor page exists."""

        value = response_data.get(
            "hasMoreResults"
        )

        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return (
                value.strip().lower()
                == "true"
            )

        return False

    @staticmethod
    def _build_earning_code_lookup(
        earning_records: list[
            dict[str, Any]
        ],
    ) -> dict[str, str]:
        """Index canonical Paycor earning codes."""

        earning_codes: dict[str, str] = {}

        for earning in earning_records:
            earning_code = str(
                earning.get("code")
                or earning.get(
                    "globalEarningCode"
                )
                or earning.get(
                    "earningCode"
                )
                or ""
            ).strip()

            if not earning_code:
                continue

            normalized_code = (
                earning_code.upper()
            )

            existing_code = earning_codes.get(
                normalized_code
            )

            if (
                existing_code is not None
                and existing_code != earning_code
            ):
                raise PaycorTimesheetServiceError(
                    "Multiple Paycor earnings "
                    f"match code {normalized_code}"
                )

            earning_codes[
                normalized_code
            ] = earning_code

        if not earning_codes:
            raise PaycorTimesheetServiceError(
                "Paycor returned no usable earnings"
            )

        return earning_codes

    @staticmethod
    def _build_department_code_lookup(
        department_records: list[
            dict[str, Any]
        ],
    ) -> dict[str, str]:
        """
        Index unique Paycor department aliases by code.

        Duplicate names such as "Sales" are excluded because
        they cannot safely identify one department.
        """

        department_codes: dict[str, str] = {}
        ambiguous_aliases: set[str] = set()

        for department in department_records:
            department_code = str(
                department.get("code")
                or department.get(
                    "departmentCode"
                )
                or ""
            ).strip()

            if not department_code:
                continue

            aliases = {
                department_code,
                str(
                    department.get("name")
                    or ""
                ).strip(),
                str(
                    department.get("description")
                    or ""
                ).strip(),
            }

            for alias in aliases:
                if not alias:
                    continue

                normalized_alias = (
                    alias.casefold()
                )

                if (
                    normalized_alias
                    in ambiguous_aliases
                ):
                    continue

                existing_code = (
                    department_codes.get(
                        normalized_alias
                    )
                )

                if (
                    existing_code is not None
                    and existing_code
                    != department_code
                ):
                    department_codes.pop(
                        normalized_alias,
                        None,
                    )

                    ambiguous_aliases.add(
                        normalized_alias
                    )

                    continue

                department_codes[
                    normalized_alias
                ] = department_code

        if not department_codes:
            raise PaycorTimesheetServiceError(
                "Paycor returned no uniquely "
                "identifiable departments"
            )

        return department_codes