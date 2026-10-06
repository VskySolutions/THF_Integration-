"""Service for retrieving approved timesheets from Maconomy."""

import asyncio
import base64
from datetime import date
from time import monotonic
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings


AUTH_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.authentication+json; "
    "charset=utf-8; version=3.0"
)

CONTAINER_ACCEPT = (
    "application/vnd.deltek.maconomy.containers+json; "
    "charset=utf-8; version=9.0"
)

CONTAINER_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.containers+json; "
    "charset=UTF-8; version=9.0"
)


TIMESHEET_FIELDS = [
    "activitynumber",
    "approvedbysuperior",
    "employeenumber",
    "instancekey",
    "jobnumber",
    "linenumber",
    "numberday1",
    "numberday2",
    "numberday3",
    "numberday4",
    "numberday5",
    "numberday6",
    "numberday7",
    "descriptionday1",
    "descriptionday2",
    "descriptionday3",
    "descriptionday4",
    "descriptionday5",
    "descriptionday6",
    "descriptionday7",
    "periodstart",
    "taskname",
    "weektotal",
    "entityname",
    "specification4name",
]


TIMESHEET_PAGE_SIZE = 500
MAX_TIMESHEET_FILTER_PAGES = 100


class MaconomyTimesheetServiceError(Exception):
    """Raised when Maconomy timesheet retrieval fails."""


class MaconomyTimesheetService:
    """Retrieve approved timesheets from Maconomy."""

    _cached_reconnect_token: str | None = None
    _token_expires_at: float = 0.0

    _token_cache_key: (
        tuple[str, str, str] | None
    ) = None

    _token_lock = asyncio.Lock()

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
    ) -> None:
        self.client = client
        self.settings = settings

        shortname = quote(
            settings.maconomy_shortname,
            safe="",
        )

        self.timesheet_lines_url = (
            f"{settings.maconomy_url}"
            f"/maconomy-api/containers/"
            f"{shortname}/timesheetlines"
        )

    async def get_approved_timesheet_lines(
        self,
        *,
        period_start_from: date,
        period_start_to: date,
    ) -> list[dict[str, Any]]:
        """Return approved Maconomy timesheet lines."""

        if period_start_to < period_start_from:
            raise MaconomyTimesheetServiceError(
                "period_start_to must be on or after "
                "period_start_from"
            )

        return await (
            self._get_paginated_timesheet_lines(
                period_start_from=period_start_from,
                period_start_to=period_start_to,
            )
        )

    async def _headers(
        self,
    ) -> dict[str, str]:
        reconnect_token = (
            await self._get_reconnect_token()
        )

        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": (
                CONTAINER_CONTENT_TYPE
            ),
            "Authorization": (
                f"X-Reconnect {reconnect_token}"
            ),
        }

    async def _get_reconnect_token(
        self,
    ) -> str:
        cache_key = (
            self.settings.maconomy_url,
            self.settings.maconomy_shortname,
            self.settings.maconomy_username,
        )

        if (
            self.__class__
            ._cached_reconnect_token
            and self.__class__
            ._token_cache_key == cache_key
            and monotonic()
            < self.__class__
            ._token_expires_at
        ):
            return (
                self.__class__
                ._cached_reconnect_token
            )

        async with self.__class__._token_lock:
            if (
                self.__class__
                ._cached_reconnect_token
                and self.__class__
                ._token_cache_key
                == cache_key
                and monotonic()
                < self.__class__
                ._token_expires_at
            ):
                return (
                    self.__class__
                    ._cached_reconnect_token
                )

            password = (
                self.settings
                .maconomy_password
                .get_secret_value()
            )

            credentials = (
                f"{self.settings.maconomy_username}:"
                f"{password}"
            )

            encoded_credentials = (
                base64.b64encode(
                    credentials.encode("utf-8")
                ).decode("ascii")
            )

            shortname = quote(
                self.settings.maconomy_shortname,
                safe="",
            )

            authentication_url = (
                f"{self.settings.maconomy_url}"
                f"/maconomy-api/auth/"
                f"{shortname}/login"
            )

            try:
                response = await self.client.get(
                    authentication_url,
                    headers={
                        "Accept": (
                            AUTH_CONTENT_TYPE
                        ),
                        "Maconomy-Authentication": (
                            "X-Reconnect"
                        ),
                        "Authorization": (
                            "Basic "
                            f"{encoded_credentials}"
                        ),
                    },
                )

                response.raise_for_status()

            except httpx.HTTPStatusError as exc:
                raise (
                    MaconomyTimesheetServiceError(
                        "Maconomy authentication "
                        "failed "
                        f"(HTTP "
                        f"{exc.response.status_code})"
                    )
                ) from exc

            except httpx.HTTPError as exc:
                raise (
                    MaconomyTimesheetServiceError(
                        "Maconomy authentication "
                        "request failed"
                    )
                ) from exc

            reconnect_token = (
                response.headers.get(
                    "Maconomy-Reconnect",
                    "",
                ).strip()
            )

            if (
                response.status_code != 204
                or not reconnect_token
            ):
                raise (
                    MaconomyTimesheetServiceError(
                        "Invalid Maconomy "
                        "authentication response"
                    )
                )

            self.__class__._cached_reconnect_token = (
                reconnect_token
            )

            self.__class__._token_cache_key = (
                cache_key
            )

            self.__class__._token_expires_at = (
                monotonic() + (29 * 60)
            )

            return reconnect_token

    @classmethod
    def _clear_cached_token(
        cls,
    ) -> None:
        cls._cached_reconnect_token = None
        cls._token_expires_at = 0.0
        cls._token_cache_key = None

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        headers = await self._headers()

        try:
            response = await self.client.post(
                f"{self.timesheet_lines_url}"
                f"{path}",
                headers=headers,
                json=payload,
            )

            # The cached reconnect token may have
            # expired earlier than expected. Clear it
            # and retry the request once.
            if response.status_code in (
                401,
                403,
            ):
                self._clear_cached_token()

                headers = await self._headers()

                response = await self.client.post(
                    f"{self.timesheet_lines_url}"
                    f"{path}",
                    headers=headers,
                    json=payload,
                )

            response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            raise (
                MaconomyTimesheetServiceError(
                    "Maconomy timesheet request "
                    "failed "
                    f"(HTTP "
                    f"{exc.response.status_code})"
                )
            ) from exc

        except httpx.HTTPError as exc:
            raise (
                MaconomyTimesheetServiceError(
                    "Maconomy timesheet request "
                    "failed or timed out"
                )
            ) from exc

        return response
    
    async def _get_paginated_timesheet_lines(
        self,
        *,
        period_start_from: date,
        period_start_to: date,
    ) -> list[dict[str, Any]]:
        restriction = (
            self._build_approved_restriction(
                period_start_from,
                period_start_to,
            )
        )

        results: list[dict[str, Any]] = []
        offset = 0

        for _ in range(
            MAX_TIMESHEET_FILTER_PAGES
        ):
            payload = {
                "fields": TIMESHEET_FIELDS,
                "restriction": restriction,
                "offset": offset,
                "limit": TIMESHEET_PAGE_SIZE,
            }

            response = await self._post(
                "/filter",
                payload,
            )

            (
                records,
                row_count,
                row_offset,
                row_total_count,
            ) = self._parse_filter_page(
                response
            )

            results.extend(records)

            next_offset = (
                row_offset + row_count
            )

            if (
                row_total_count is not None
                and next_offset
                >= row_total_count
            ):
                return results

            if row_count == 0:
                if row_total_count is None:
                    return results

                raise (
                    MaconomyTimesheetServiceError(
                        "Maconomy timesheet filter "
                        "ended before all records "
                        "were returned"
                    )
                )

            if (
                row_total_count is None
                and row_count
                < TIMESHEET_PAGE_SIZE
            ):
                return results

            if next_offset <= offset:
                raise (
                    MaconomyTimesheetServiceError(
                        "Maconomy timesheet filter "
                        "pagination did not advance"
                    )
                )

            offset = next_offset

        raise MaconomyTimesheetServiceError(
            "Maconomy timesheet filter exceeded "
            "the maximum page limit"
        )

    @classmethod
    def _parse_filter_page(
        cls,
        response: httpx.Response,
    ) -> tuple[
        list[dict[str, Any]],
        int,
        int,
        int | None,
    ]:
        try:
            filter_pane = (
                response.json()
                ["panes"]["filter"]
            )

            meta = filter_pane["meta"]
            raw_records = (
                filter_pane["records"]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise (
                MaconomyTimesheetServiceError(
                    "Invalid Maconomy timesheet "
                    "filter response"
                )
            ) from exc

        if (
            not isinstance(meta, dict)
            or not isinstance(
                raw_records,
                list,
            )
        ):
            raise (
                MaconomyTimesheetServiceError(
                    "Invalid Maconomy timesheet "
                    "filter response"
                )
            )

        row_count = (
            cls._parse_filter_count(
                meta.get("rowCount"),
                "rowCount",
            )
        )

        row_offset = (
            cls._parse_filter_count(
                meta.get("rowOffset"),
                "rowOffset",
            )
        )

        row_total_count = (
            cls._parse_optional_filter_count(
                meta.get("rowTotalCount"),
                "rowTotalCount",
            )
        )

        if row_count != len(raw_records):
            raise (
                MaconomyTimesheetServiceError(
                    "Maconomy timesheet filter "
                    "returned an inconsistent "
                    "row count"
                )
            )

        records: list[
            dict[str, Any]
        ] = []

        for raw_record in raw_records:
            if not isinstance(
                raw_record,
                dict,
            ):
                raise (
                    MaconomyTimesheetServiceError(
                        "Invalid Maconomy "
                        "timesheet record"
                    )
                )

            record_data = raw_record.get(
                "data"
            )

            if not isinstance(
                record_data,
                dict,
            ):
                raise (
                    MaconomyTimesheetServiceError(
                        "Invalid Maconomy "
                        "timesheet record"
                    )
                )

            records.append(
                dict(record_data)
            )

        return (
            records,
            row_count,
            row_offset,
            row_total_count,
        )

    @staticmethod
    def _build_approved_restriction(
        period_start_from: date,
        period_start_to: date,
    ) -> str:
        start_date = (
            f"date("
            f"{period_start_from.year},"
            f"{period_start_from.month},"
            f"{period_start_from.day}"
            f")"
        )

        end_date = (
            f"date("
            f"{period_start_to.year},"
            f"{period_start_to.month},"
            f"{period_start_to.day}"
            f")"
        )

        return (
            "approvedbysuperior "
            f"and periodstart>={start_date} "
            f"and periodstart<={end_date}"
        )

    @staticmethod
    def _parse_filter_count(
        value: Any,
        field_name: str,
    ) -> int:
        if (
            isinstance(value, str)
            and value.strip().isdigit()
        ):
            value = int(value.strip())

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise (
                MaconomyTimesheetServiceError(
                    "Invalid Maconomy timesheet "
                    f"{field_name}"
                )
            )

        return value

    @classmethod
    def _parse_optional_filter_count(
        cls,
        value: Any,
        field_name: str,
    ) -> int | None:
        if value is None or value == "":
            return None

        return cls._parse_filter_count(
            value,
            field_name,
        )