"""Service for writing timesheet data to Paycor."""

from datetime import date
from typing import Any, Literal
from urllib.parse import urljoin

import httpx


from app.core.config import Settings, get_settings


class PaycorTimesheetServiceError(Exception):
    """Raised when Paycor timesheet processing fails."""


class PaycorTimesheetSubmissionUnknownError(
    PaycorTimesheetServiceError
):
    """Raised when Paycor may have received a submission."""


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
        dict[str, str],
    ]:
        """Retrieve earnings, departments, and employee pay groups."""

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

                employee_paygroup_records = (
                    await self._get_all_employee_paygroups(
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
            self._build_employee_paygroup_lookup(
                employee_paygroup_records
            ),
        )

    async def get_pay_schedules(
        self,
        *,
        pay_group_ids: set[str],
        start_date: date,
        end_date: date,
    ) -> dict[
        str,
        list[dict[str, date]],
    ]:
        """Return validated Paycor periods for each pay group."""

        if end_date < start_date:
            raise PaycorTimesheetServiceError(
                "Pay-schedule end date must be on or "
                "after its start date"
            )

        normalized_pay_group_ids = {
            normalized_id
            for pay_group_id in pay_group_ids
            if (
                normalized_id
                := str(pay_group_id).strip()
            )
        }

        if not normalized_pay_group_ids:
            raise PaycorTimesheetServiceError(
                "At least one Paycor pay group is required"
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

                schedules_by_group: dict[
                    str,
                    list[dict[str, date]],
                ] = {}

                for pay_group_id in sorted(
                    normalized_pay_group_ids
                ):
                    schedule_records = await (
                        self._get_all_pay_schedules(
                            client=client,
                            access_token=access_token,
                            pay_group_id=pay_group_id,
                            start_date=start_date,
                            end_date=end_date,
                        )
                    )

                    schedules_by_group[
                        pay_group_id
                    ] = self._build_pay_schedule_periods(
                        schedule_records,
                        pay_group_id=pay_group_id,
                    )

        except PaycorTimesheetServiceError:
            raise
        except httpx.HTTPError as exc:
            raise PaycorTimesheetServiceError(
                "Unable to retrieve Paycor pay schedules"
            ) from exc

        return schedules_by_group


    async def submit_payroll_hours(
        self,
        payload: dict[str, Any],
        *,
        submission_mode: Literal[
            "append",
            "replace",
        ],
    ) -> dict[str, Any]:
        """Submit payroll hours to Paycor Paygrid."""

        if submission_mode == "append":
            submission_params = {
                "appendData": "true",
            }
        elif submission_mode == "replace":
            submission_params = {
                "replaceData": "true",
            }
        else:
            raise PaycorTimesheetServiceError(
                "Unsupported Paycor payroll-hours "
                f"submission mode: {submission_mode}"
            )

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
                    params=submission_params,
                    headers=self._get_api_headers(
                        access_token
                    ),
                    json=payload,
                )

        except httpx.RequestError as exc:
            request_url = str(
                exc.request.url
            )

            if "/payrollhours" in request_url:
                raise PaycorTimesheetSubmissionUnknownError(
                    "Paycor payroll-hours submission "
                    "status is unknown"
                ) from exc

            raise PaycorTimesheetServiceError(
                "Unable to connect to Paycor before "
                "submitting payroll hours"
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
            "submissionMode": submission_mode,
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

    async def _get_all_employee_paygroups(
        self,
        *,
        client: httpx.AsyncClient,
        access_token: str,
    ) -> list[dict[str, Any]]:
        """Retrieve active employees and their Paycor pay groups."""

        initial_url = (
            f"{self.settings.paycor_url.rstrip('/')}"
            "/v1/legalentities/"
            f"{self.settings.paycor_legal_entity_id}"
            "/employees"
        )

        return await self._get_all_paginated_records(
            client=client,
            access_token=access_token,
            initial_url=initial_url,
            initial_params=[
                ("include", "Position"),
                ("statusFilter", "Active"),
            ],
            resource_name="employee pay groups",
        )

    async def _get_all_pay_schedules(
        self,
        *,
        client: httpx.AsyncClient,
        access_token: str,
        pay_group_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Retrieve Paycor periods for one pay group."""

        initial_url = (
            f"{self.settings.paycor_url.rstrip('/')}"
            "/v1/legalentities/"
            f"{self.settings.paycor_legal_entity_id}"
            "/payschedule"
        )

        return await self._get_all_paginated_records(
            client=client,
            access_token=access_token,
            initial_url=initial_url,
            initial_params=[
                ("payGroupId", pay_group_id),
                (
                    "asOfDate",
                    start_date.isoformat(),
                ),
                (
                    "untilDate",
                    end_date.isoformat(),
                ),
            ],
            resource_name=(
                "pay schedule for pay group "
                f"{pay_group_id}"
            ),
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

    @staticmethod
    def _build_employee_paygroup_lookup(
        employee_records: list[
            dict[str, Any]
        ],
    ) -> dict[str, str]:
        """Index Paycor pay-group IDs by employee number."""

        paygroup_by_employee: dict[str, str] = {}

        for employee in employee_records:
            employee_number = str(
                employee.get("employeeNumber")
                or ""
            ).strip()

            pay_group_id = str(
                employee.get("payGroupId")
                or ""
            ).strip()

            if not employee_number or not pay_group_id:
                continue

            existing_pay_group_id = (
                paygroup_by_employee.get(
                    employee_number
                )
            )

            if (
                existing_pay_group_id is not None
                and existing_pay_group_id
                != pay_group_id
            ):
                raise PaycorTimesheetServiceError(
                    "Multiple Paycor pay groups found "
                    "for employee number "
                    f"{employee_number}"
                )

            paygroup_by_employee[
                employee_number
            ] = pay_group_id

        if not paygroup_by_employee:
            raise PaycorTimesheetServiceError(
                "Paycor returned no usable employee "
                "pay groups"
            )

        return paygroup_by_employee

    @classmethod
    def _build_pay_schedule_periods(
        cls,
        schedule_records: list[
            dict[str, Any]
        ],
        *,
        pay_group_id: str,
    ) -> list[dict[str, date]]:
        """Normalize and validate one pay group's periods."""

        periods: list[dict[str, date]] = []

        for schedule in schedule_records:
            returned_pay_group_id = str(
                schedule.get("payGroupId")
                or pay_group_id
            ).strip()

            if returned_pay_group_id != pay_group_id:
                raise PaycorTimesheetServiceError(
                    "Paycor pay schedule returned a "
                    "different pay group"
                )

            pay_period_start = (
                cls._parse_pay_schedule_date(
                    schedule.get("payPeriodStart"),
                    "payPeriodStart",
                )
            )
            pay_period_end = (
                cls._parse_pay_schedule_date(
                    schedule.get("payPeriodEnd"),
                    "payPeriodEnd",
                )
            )

            if pay_period_end < pay_period_start:
                raise PaycorTimesheetServiceError(
                    "Paycor pay period end is before "
                    "its start for pay group "
                    f"{pay_group_id}"
                )

            periods.append(
                {
                    "payPeriodStart": pay_period_start,
                    "payPeriodEnd": pay_period_end,
                }
            )

        periods.sort(
            key=lambda period: (
                period["payPeriodStart"],
                period["payPeriodEnd"],
            )
        )

        if not periods:
            raise PaycorTimesheetServiceError(
                "Paycor returned no pay periods for "
                f"pay group {pay_group_id}"
            )

        for previous, current in zip(
            periods,
            periods[1:],
        ):
            if (
                current["payPeriodStart"]
                <= previous["payPeriodEnd"]
            ):
                raise PaycorTimesheetServiceError(
                    "Paycor returned overlapping pay "
                    "periods for pay group "
                    f"{pay_group_id}"
                )

        return periods

    @staticmethod
    def _parse_pay_schedule_date(
        value: Any,
        field_name: str,
    ) -> date:
        """Parse one required Paycor pay-schedule date."""

        if not isinstance(value, str) or not value.strip():
            raise PaycorTimesheetServiceError(
                "Paycor pay schedule is missing "
                f"{field_name}"
            )

        try:
            return date.fromisoformat(
                value.strip()[:10]
            )
        except ValueError as exc:
            raise PaycorTimesheetServiceError(
                "Paycor pay schedule contains invalid "
                f"{field_name}"
            ) from exc
