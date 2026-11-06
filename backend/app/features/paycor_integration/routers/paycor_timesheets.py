"""Maconomy-to-Paycor timesheet routes."""

import logging

from collections.abc import AsyncIterator
from datetime import (
    date,
    datetime,
    timedelta,
)
from typing import Annotated, Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.features.auth.dependencies import (
    require_api_key,
)
from app.features.paycor_integration.mappers.timesheet_mapper import (
    map_maconomy_timesheets,
    map_timesheets_to_paycor,
)
from app.features.paycor_integration.services.maconomy_timesheet_service import (
    MaconomyTimesheetService,
    MaconomyTimesheetServiceError,
)
from app.features.paycor_integration.services.paycor_timesheet_service import (
    PaycorTimesheetService,
    PaycorTimesheetServiceError,
)
from app.features.paycor_integration.services.paycor_timesheet_sync_service import (
    NoApprovedTimesheetsError,
    PaycorTimesheetSyncService,
    TimesheetReconciliationRequiredError,
)
from app.features.paycor_integration.services.timesheet_integration_log_service import (
    TimesheetSubmissionBlockedError,
)
from app.features.paycor_integration.services.timesheet_calculation_service import (
    calculate_all_weekly_earnings,
)


LOGGER = logging.getLogger(__name__)


TEMPORARY_EARNING_CODE_FALLBACKS: dict[str, str] = {}


router = APIRouter(
    prefix="/paycor/timesheets",
    tags=["paycor-timesheet-integration"],
    dependencies=[Depends(require_api_key)],
)


async def get_maconomy_service(
) -> AsyncIterator[MaconomyTimesheetService]:
    """Provide a Maconomy timesheet service."""

    async with httpx.AsyncClient(
        timeout=60.0
    ) as client:
        yield MaconomyTimesheetService(
            client=client,
            settings=get_settings(),
        )


MaconomyServiceDependency = Annotated[
    MaconomyTimesheetService,
    Depends(get_maconomy_service),
]

DatabaseSession = Annotated[
    AsyncSession,
    Depends(get_db),
]


def _validate_date_range(
    start_date: date,
    end_date: date,
) -> None:
    """Validate the requested date range."""

    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "end_date must be on or after "
                "start_date"
            ),
        )


def _validate_week_date_range(
    start_date: date,
    end_date: date,
) -> None:
    """Validate one complete Monday-through-Sunday week."""

    _validate_date_range(
        start_date,
        end_date,
    )

    if end_date - start_date != timedelta(days=6):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The date range must contain exactly "
                "seven days"
            ),
        )

    if start_date.weekday() != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be a Monday",
        )

    if end_date.weekday() != 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date must be a Sunday",
        )


def _filter_available_earnings(
    entries: list[dict[str, Any]],
    earning_codes: dict[str, str],
) -> tuple[
    list[dict[str, Any]],
    set[str],
    set[tuple[str, str]],
]:
    """Remove unavailable earnings and apply sandbox fallbacks."""

    valid_entries: list[dict[str, Any]] = []
    skipped_codes: set[str] = set()
    temporary_mappings: set[
        tuple[str, str]
    ] = set()

    for entry in entries:
        requested_code = str(
            entry.get("earningCode") or ""
        ).strip().upper()

        if not requested_code:
            skipped_codes.add("<missing>")
            continue

        if requested_code in earning_codes:
            valid_entries.append(entry)
            continue

        fallback_code = (
            TEMPORARY_EARNING_CODE_FALLBACKS.get(
                requested_code
            )
        )

        if (
            fallback_code is None
            or fallback_code
            not in earning_codes
        ):
            skipped_codes.add(requested_code)
            continue

        mapped_code = earning_codes[
            fallback_code
        ]

        valid_entries.append(
            {
                **entry,
                "earningCode": mapped_code,
            }
        )

        temporary_mappings.add(
            (
                requested_code,
                mapped_code,
            )
        )

    return (
        valid_entries,
        skipped_codes,
        temporary_mappings,
    )


def _set_warning_header(
    *,
    response: Response,
    skipped_tasks: list[str],
    skipped_earnings: set[str],
    temporary_mappings: set[
        tuple[str, str]
    ],
) -> None:
    """Add one combined processing-warning header."""

    warnings: list[str] = []

    if skipped_tasks:
        tasks = ", ".join(
            sorted(set(skipped_tasks))
        )

        warnings.append(
            f"Maconomy tasks skipped: {tasks}"
        )

    if skipped_earnings:
        earnings = ", ".join(
            sorted(skipped_earnings)
        )

        warnings.append(
            "Unavailable Paycor earnings "
            f"skipped: {earnings}"
        )

    if temporary_mappings:
        mappings = ", ".join(
            f"{source}->{target}"
            for source, target
            in sorted(temporary_mappings)
        )

        warnings.append(
            "Temporary earning mappings "
            f"applied: {mappings}"
        )

    if warnings:
        warning_message = "; ".join(warnings)

        response.headers[
            "X-Timesheet-Warning"
        ] = warning_message

        LOGGER.warning(warning_message)


def _set_grouped_warning_header(
    *,
    response: Response,
    warnings: dict[str, Any],
) -> None:
    """Expose grouped synchronization warnings consistently."""

    temporary_mappings = {
        (
            str(mapping.get("source") or ""),
            str(mapping.get("target") or ""),
        )
        for mapping in warnings.get(
            "temporaryMappings",
            [],
        )
        if isinstance(mapping, dict)
    }

    _set_warning_header(
        response=response,
        skipped_tasks=list(
            warnings.get("skippedTasks", [])
        ),
        skipped_earnings=set(
            warnings.get(
                "skippedEarnings",
                [],
            )
        ),
        temporary_mappings=(
            temporary_mappings
        ),
    )


@router.get(
    "/approved",
    response_model=dict[str, Any],
)
async def get_approved_timesheet_lines(
    maconomy_service: MaconomyServiceDependency,
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> dict[str, Any]:
    """Retrieve approved Maconomy timesheets."""

    _validate_date_range(
        start_date,
        end_date,
    )

    try:
        records = await (
            maconomy_service
            .get_approved_timesheet_lines(
                period_start_from=start_date,
                period_start_to=end_date,
            )
        )

    except MaconomyTimesheetServiceError as exc:
        LOGGER.exception(
            "Approved Maconomy timesheet "
            "retrieval failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return {
        "periodStartFrom": start_date.isoformat(),
        "periodStartTo": end_date.isoformat(),
        "totalRecords": len(records),
        "records": records,
    }


@router.get(
    "/paygrid-payload",
    response_model=dict[str, Any],
)
async def get_paygrid_payload(
    response: Response,
    maconomy_service: MaconomyServiceDependency,
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> dict[str, Any]:
    """Fetch approved timesheets and build a Paygrid payload."""

    _validate_date_range(
        start_date,
        end_date,
    )

    settings = get_settings()

    paycor_service = PaycorTimesheetService(
        settings=settings
    )

    try:
        maconomy_records = await (
            maconomy_service
            .get_approved_timesheet_lines(
                period_start_from=start_date,
                period_start_to=end_date,
            )
        )

        if not maconomy_records:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "No approved Maconomy timesheets "
                    "were found for the selected dates"
                ),
            )

        entity_descriptions_by_code = await (
            maconomy_service
            .get_entity_descriptions_by_code()
        )

        (
            earning_codes,
            department_codes,
            paygroup_by_employee,
        ) = await (
            paycor_service
            .get_timesheet_reference_data()
        )

        (
            daily_entries,
            skipped_tasks,
        ) = map_maconomy_timesheets(
            maconomy_records,
            entity_descriptions_by_code=(
                entity_descriptions_by_code
            ),
            department_codes_by_name=(
                department_codes
            ),
        )

        if not daily_entries:
            tasks = (
                ", ".join(
                    sorted(set(skipped_tasks))
                )
                or "<none>"
            )

            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=(
                    "No valid Maconomy timesheet "
                    "entries remain after mapping. "
                    f"Skipped tasks: {tasks}"
                ),
            )

        calculated_entries = (
            calculate_all_weekly_earnings(
                daily_entries
            )
        )

        (
            calculated_entries,
            skipped_earnings,
            temporary_mappings,
        ) = _filter_available_earnings(
            calculated_entries,
            earning_codes,
        )

        if not calculated_entries:
            earnings = (
                ", ".join(
                    sorted(skipped_earnings)
                )
                or "<none>"
            )

            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=(
                    "No calculated timesheet entries "
                    "remain after Paycor earning "
                    f"validation: {earnings}"
                ),
            )

        payload = map_timesheets_to_paycor(
            calculated_entries,
            earning_codes=earning_codes,
            paygroup_by_employee=(
                paygroup_by_employee
            ),
            process_id=str(uuid4()),
        )

        _set_warning_header(
            response=response,
            skipped_tasks=skipped_tasks,
            skipped_earnings=(
                skipped_earnings
            ),
            temporary_mappings=(
                temporary_mappings
            ),
        )

        return payload

    except HTTPException:
        raise

    except (
        MaconomyTimesheetServiceError,
        PaycorTimesheetServiceError,
    ) as exc:
        LOGGER.exception(
            "Timesheet external-service "
            "processing failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        LOGGER.exception(
            "Timesheet payload generation "
            "failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=str(exc),
        ) from exc


@router.post(
    "/paygrid",
    response_model=dict[str, Any],
)
async def submit_paycor_paygrid(
    response: Response,
    maconomy_service: MaconomyServiceDependency,
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> dict[str, Any]:
    """Build and submit approved payroll hours to Paycor."""

    payload = await get_paygrid_payload(
        response=response,
        maconomy_service=maconomy_service,
        start_date=start_date,
        end_date=end_date,
    )

    try:
        return await (
            PaycorTimesheetService()
            .submit_payroll_hours(
                payload,
                submission_mode="append",
            )
        )

    except PaycorTimesheetServiceError as exc:
        LOGGER.exception(
            "Paycor Paygrid submission failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post(
    "/sync/weekly",
    response_model=dict[str, Any],
)
async def sync_previous_week_to_paycor(
    response: Response,
    maconomy_service: MaconomyServiceDependency,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Build and append the previous Eastern-time week."""

    local_today = datetime.now(
        ZoneInfo("America/New_York")
    ).date()
    current_monday = (
        local_today
        - timedelta(
            days=local_today.weekday()
        )
    )
    start_date = (
        current_monday
        - timedelta(days=7)
    )
    end_date = (
        current_monday
        - timedelta(days=1)
    )

    sync_service = PaycorTimesheetSyncService(
        maconomy_service=maconomy_service,
        paycor_service=PaycorTimesheetService(),
    )

    try:
        result = await (
            sync_service.submit_new_groups(
                session,
                start_date=start_date,
                end_date=end_date,
            )
        )

    except NoApprovedTimesheetsError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (
        TimesheetReconciliationRequiredError,
        TimesheetSubmissionBlockedError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (
        MaconomyTimesheetServiceError,
        PaycorTimesheetServiceError,
    ) as exc:
        LOGGER.exception(
            "Weekly Paycor timesheet synchronization "
            "failed: %s",
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=str(exc),
        ) from exc

    _set_grouped_warning_header(
        response=response,
        warnings=result["warnings"],
    )

    return result


@router.post(
    "/paygrid-by-daterange",
    response_model=dict[str, Any],
)
async def retry_paygrid_by_date_range(
    response: Response,
    maconomy_service: MaconomyServiceDependency,
    session: DatabaseSession,
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> dict[str, Any]:
    """Append or replace grouped batches for one source week."""

    _validate_week_date_range(
        start_date,
        end_date,
    )

    sync_service = PaycorTimesheetSyncService(
        maconomy_service=maconomy_service,
        paycor_service=PaycorTimesheetService(),
    )

    try:
        result = await (
            sync_service.retry_groups(
                session,
                start_date=start_date,
                end_date=end_date,
            )
        )

    except NoApprovedTimesheetsError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (
        TimesheetReconciliationRequiredError,
        TimesheetSubmissionBlockedError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (
        MaconomyTimesheetServiceError,
        PaycorTimesheetServiceError,
    ) as exc:
        LOGGER.exception(
            "Paycor date-range batch rebuild failed: %s",
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=str(exc),
        ) from exc

    _set_grouped_warning_header(
        response=response,
        warnings=result["warnings"],
    )

    return result
