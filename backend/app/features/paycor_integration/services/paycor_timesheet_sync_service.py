"""Orchestrate grouped Maconomy-to-Paycor time synchronization."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.paycor_integration.constants import (
    TimesheetSubmissionMode,
    TimesheetSubmissionStatus,
)
from app.features.paycor_integration.mappers.timesheet_mapper import (
    PayPeriodGroupKey,
    assign_employee_paygroups,
    assign_pay_periods,
    group_timesheets_by_pay_period,
    map_maconomy_timesheets,
    map_timesheets_to_paycor,
)
from app.features.paycor_integration.services.maconomy_timesheet_service import (
    MaconomyTimesheetService,
)
from app.features.paycor_integration.services.paycor_timesheet_service import (
    PaycorTimesheetService,
    PaycorTimesheetServiceError,
    PaycorTimesheetSubmissionUnknownError,
)
from app.features.paycor_integration.services.timesheet_batch_service import (
    get_or_create_batch,
    mark_batch_accepted,
)
from app.features.paycor_integration.services.timesheet_integration_log_service import (
    complete_log,
    create_submitting_log,
    get_latest_accepted_log,
    get_latest_log,
)
from app.features.paycor_integration.services.timesheet_calculation_service import (
    calculate_all_weekly_earnings,
)


TEMPORARY_EARNING_CODE_FALLBACKS: dict[str, str] = {}


class PaycorTimesheetSyncServiceError(ValueError):
    """Raised when a grouped synchronization cannot be built."""


class NoApprovedTimesheetsError(
    PaycorTimesheetSyncServiceError
):
    """Raised when Maconomy returns no approved time."""


class TimesheetReconciliationRequiredError(
    PaycorTimesheetSyncServiceError
):
    """Raised when an uncertain batch must be reviewed."""


class PaycorTimesheetSyncService:
    """Build and submit pay-period-specific payroll batches."""

    def __init__(
        self,
        *,
        maconomy_service: MaconomyTimesheetService,
        paycor_service: PaycorTimesheetService,
    ) -> None:
        self.maconomy_service = maconomy_service
        self.paycor_service = paycor_service

    async def build_grouped_payloads(
        self,
        *,
        start_date: date,
        end_date: date,
        process_ids_by_group: dict[
            PayPeriodGroupKey,
            str,
        ] | None = None,
    ) -> dict[str, Any]:
        """Build validated payloads grouped by Paycor pay period."""

        if end_date < start_date:
            raise PaycorTimesheetSyncServiceError(
                "end_date must be on or after start_date"
            )

        maconomy_records = await (
            self.maconomy_service
            .get_approved_timesheet_lines(
                period_start_from=start_date,
                period_start_to=end_date,
            )
        )

        if not maconomy_records:
            raise NoApprovedTimesheetsError(
                "No approved Maconomy timesheets were "
                "found for the selected dates"
            )

        entity_descriptions_by_code = await (
            self.maconomy_service
            .get_entity_descriptions_by_code()
        )

        (
            earning_codes,
            department_codes,
            paygroup_by_employee,
        ) = await (
            self.paycor_service
            .get_timesheet_reference_data()
        )

        daily_entries, skipped_tasks = (
            map_maconomy_timesheets(
                maconomy_records,
                entity_descriptions_by_code=(
                    entity_descriptions_by_code
                ),
                department_codes_by_name=(
                    department_codes
                ),
            )
        )

        if not daily_entries:
            tasks = (
                ", ".join(skipped_tasks)
                or "<none>"
            )
            raise PaycorTimesheetSyncServiceError(
                "No valid Maconomy timesheet entries "
                "remain after mapping. "
                f"Skipped tasks: {tasks}"
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
        ) = self._filter_available_earnings(
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
            raise PaycorTimesheetSyncServiceError(
                "No calculated timesheet entries "
                "remain after Paycor earning "
                f"validation: {earnings}"
            )

        calculated_entries = (
            assign_employee_paygroups(
                calculated_entries,
                paygroup_by_employee=(
                    paygroup_by_employee
                ),
            )
        )

        date_worked_values = [
            entry["dateWorked"]
            for entry in calculated_entries
        ]
        pay_group_ids = {
            str(entry["payGroupId"])
            for entry in calculated_entries
        }

        pay_schedules_by_group = await (
            self.paycor_service.get_pay_schedules(
                pay_group_ids=pay_group_ids,
                start_date=min(date_worked_values),
                end_date=max(date_worked_values),
            )
        )

        calculated_entries = assign_pay_periods(
            calculated_entries,
            pay_schedules_by_group=(
                pay_schedules_by_group
            ),
        )

        grouped_entries = (
            group_timesheets_by_pay_period(
                calculated_entries
            )
        )

        batches: list[dict[str, Any]] = []
        process_ids: set[str] = set()

        for group_key in sorted(grouped_entries):
            (
                pay_group_id,
                pay_period_start,
                pay_period_end,
            ) = group_key

            process_id = str(
                (
                    process_ids_by_group
                    or {}
                ).get(
                    group_key,
                    uuid4(),
                )
            ).strip()

            if not process_id:
                raise PaycorTimesheetSyncServiceError(
                    "Paycor process ID is required"
                )

            if process_id in process_ids:
                raise PaycorTimesheetSyncServiceError(
                    "Each Paycor group must use a "
                    "different process ID"
                )

            process_ids.add(process_id)
            group_entries = grouped_entries[
                group_key
            ]
            group_paygroups = {
                str(entry["employeeNumber"]): (
                    pay_group_id
                )
                for entry in group_entries
            }

            payload = map_timesheets_to_paycor(
                group_entries,
                earning_codes=earning_codes,
                paygroup_by_employee=(
                    group_paygroups
                ),
                process_id=process_id,
            )

            self._validate_group_payload(
                payload,
                pay_group_id=pay_group_id,
            )

            batches.append(
                {
                    "payGroupId": pay_group_id,
                    "payPeriodStart": (
                        pay_period_start.isoformat()
                    ),
                    "payPeriodEnd": (
                        pay_period_end.isoformat()
                    ),
                    "processId": process_id,
                    "payload": payload,
                }
            )

        if not batches:
            raise PaycorTimesheetSyncServiceError(
                "No Paycor payroll-hours batches were built"
            )

        return {
            "periodStartFrom": start_date.isoformat(),
            "periodStartTo": end_date.isoformat(),
            "batchCount": len(batches),
            "batches": batches,
            "warnings": {
                "skippedTasks": skipped_tasks,
                "skippedEarnings": sorted(
                    skipped_earnings
                ),
                "temporaryMappings": [
                    {
                        "source": source,
                        "target": target,
                    }
                    for source, target in sorted(
                        temporary_mappings
                    )
                ],
            },
        }

    async def submit_new_groups(
        self,
        session: AsyncSession,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Build and append all groups for one source range."""

        grouped_payloads = await (
            self.build_grouped_payloads(
                start_date=start_date,
                end_date=end_date,
            )
        )

        prepared_batches = await (
            self._prepare_batches(
                session,
                grouped_payloads=grouped_payloads,
                replace_accepted=False,
            )
        )

        return await self._submit_prepared_batches(
            session,
            grouped_payloads=grouped_payloads,
            prepared_batches=prepared_batches,
        )

    async def retry_groups(
        self,
        session: AsyncSession,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Append new groups and replace accepted groups."""

        grouped_payloads = await (
            self.build_grouped_payloads(
                start_date=start_date,
                end_date=end_date,
            )
        )

        prepared_batches = await (
            self._prepare_batches(
                session,
                grouped_payloads=grouped_payloads,
                replace_accepted=True,
            )
        )

        return await self._submit_prepared_batches(
            session,
            grouped_payloads=grouped_payloads,
            prepared_batches=prepared_batches,
        )

    async def _prepare_batches(
        self,
        session: AsyncSession,
        *,
        grouped_payloads: dict[str, Any],
        replace_accepted: bool,
    ) -> list[dict[str, Any]]:
        """Resolve persisted process and retry state for all groups."""

        try:
            legal_entity_id = int(
                str(
                    self.paycor_service.settings
                    .paycor_legal_entity_id
                ).strip()
            )
        except (TypeError, ValueError) as exc:
            raise PaycorTimesheetSyncServiceError(
                "Paycor legal entity ID must be an integer"
            ) from exc

        source_start_date = date.fromisoformat(
            grouped_payloads["periodStartFrom"]
        )
        source_end_date = date.fromisoformat(
            grouped_payloads["periodStartTo"]
        )
        prepared_batches: list[
            dict[str, Any]
        ] = []

        for payload_batch in grouped_payloads[
            "batches"
        ]:
            pay_period_start = date.fromisoformat(
                payload_batch["payPeriodStart"]
            )
            pay_period_end = date.fromisoformat(
                payload_batch["payPeriodEnd"]
            )
            database_batch, _ = await (
                get_or_create_batch(
                    session,
                    legal_entity_id=legal_entity_id,
                    source_start_date=(
                        source_start_date
                    ),
                    source_end_date=source_end_date,
                    pay_group_id=(
                        payload_batch["payGroupId"]
                    ),
                    pay_period_start=pay_period_start,
                    pay_period_end=pay_period_end,
                )
            )

            latest_log = await get_latest_log(
                session,
                batch_id=database_batch.id,
            )

            if (
                latest_log is not None
                and latest_log.status
                in {
                    TimesheetSubmissionStatus.SUBMITTING,
                    TimesheetSubmissionStatus.UNKNOWN,
                }
            ):
                raise TimesheetReconciliationRequiredError(
                    "Paycor timesheet batch requires "
                    "manual reconciliation for pay group "
                    f"{payload_batch['payGroupId']} and "
                    "pay period "
                    f"{payload_batch['payPeriodStart']} to "
                    f"{payload_batch['payPeriodEnd']}"
                )

            accepted_process_id = (
                database_batch.accepted_process_id
            )

            if accepted_process_id is None:
                accepted_log = await (
                    get_latest_accepted_log(
                        session,
                        batch_id=database_batch.id,
                    )
                )

                if accepted_log is not None:
                    accepted_process_id = (
                        accepted_log.process_id
                    )
                    await mark_batch_accepted(
                        session,
                        database_batch,
                        process_id=(
                            accepted_process_id
                        ),
                    )

            if accepted_process_id is not None:
                if not replace_accepted:
                    prepared_batches.append(
                        {
                            "databaseBatch": (
                                database_batch
                            ),
                            "payloadBatch": (
                                payload_batch
                            ),
                            "skip": True,
                        }
                    )
                    continue

                process_id = accepted_process_id
                submission_mode = (
                    TimesheetSubmissionMode.REPLACE
                )
            else:
                try:
                    process_id = uuid.UUID(
                        payload_batch["processId"]
                    )
                except (TypeError, ValueError) as exc:
                    raise PaycorTimesheetSyncServiceError(
                        "Generated Paycor process ID is invalid"
                    ) from exc

                submission_mode = (
                    TimesheetSubmissionMode.APPEND
                )

            normalized_process_id = str(
                process_id
            )
            payload_batch[
                "processId"
            ] = normalized_process_id
            payload_batch["payload"][
                "processId"
            ] = normalized_process_id

            prepared_batches.append(
                {
                    "databaseBatch": database_batch,
                    "payloadBatch": payload_batch,
                    "processId": process_id,
                    "submissionMode": submission_mode,
                    "skip": False,
                }
            )

        await session.commit()
        return prepared_batches

    async def _submit_prepared_batches(
        self,
        session: AsyncSession,
        *,
        grouped_payloads: dict[str, Any],
        prepared_batches: list[
            dict[str, Any]
        ],
    ) -> dict[str, Any]:
        """Submit preflighted groups and persist every attempt."""

        submission_results: list[
            dict[str, Any]
        ] = []

        for prepared_batch in prepared_batches:
            payload_batch = prepared_batch[
                "payloadBatch"
            ]

            if prepared_batch["skip"]:
                submission_results.append(
                    {
                        "payGroupId": (
                            payload_batch["payGroupId"]
                        ),
                        "payPeriodStart": (
                            payload_batch[
                                "payPeriodStart"
                            ]
                        ),
                        "payPeriodEnd": (
                            payload_batch[
                                "payPeriodEnd"
                            ]
                        ),
                        "processId": str(
                            prepared_batch[
                                "databaseBatch"
                            ].accepted_process_id
                        ),
                        "result": {
                            "status": "SKIPPED",
                            "message": (
                                "Batch was already accepted"
                            ),
                        },
                    }
                )
                continue

            database_batch = prepared_batch[
                "databaseBatch"
            ]
            process_id = prepared_batch[
                "processId"
            ]
            submission_mode = prepared_batch[
                "submissionMode"
            ]
            payload = payload_batch["payload"]

            integration_log = await (
                create_submitting_log(
                    session,
                    batch_id=database_batch.id,
                    process_id=process_id,
                    submission_mode=submission_mode,
                    payload=payload,
                )
            )

            try:
                result = await (
                    self.paycor_service
                    .submit_payroll_hours(
                        payload,
                        submission_mode=(
                            submission_mode
                            .value.lower()
                        ),
                    )
                )

            except PaycorTimesheetSubmissionUnknownError as exc:
                await complete_log(
                    session,
                    integration_log,
                    status=(
                        TimesheetSubmissionStatus.UNKNOWN
                    ),
                    http_status=None,
                    response=None,
                    message=str(exc),
                )
                raise
            except PaycorTimesheetServiceError as exc:
                await complete_log(
                    session,
                    integration_log,
                    status=(
                        TimesheetSubmissionStatus.FAILED
                    ),
                    http_status=None,
                    response=None,
                    message=str(exc),
                )
                raise

            await complete_log(
                session,
                integration_log,
                status=(
                    TimesheetSubmissionStatus.ACCEPTED
                ),
                http_status=result["httpStatus"],
                response=result["paycorResponse"],
                message=None,
            )
            await mark_batch_accepted(
                session,
                database_batch,
                process_id=process_id,
            )

            submission_results.append(
                {
                    "payGroupId": (
                        payload_batch["payGroupId"]
                    ),
                    "payPeriodStart": (
                        payload_batch[
                            "payPeriodStart"
                        ]
                    ),
                    "payPeriodEnd": (
                        payload_batch[
                            "payPeriodEnd"
                        ]
                    ),
                    "processId": str(process_id),
                    "result": result,
                }
            )

        return {
            "periodStartFrom": (
                grouped_payloads[
                    "periodStartFrom"
                ]
            ),
            "periodStartTo": (
                grouped_payloads[
                    "periodStartTo"
                ]
            ),
            "batchCount": len(
                submission_results
            ),
            "submissions": submission_results,
            "warnings": grouped_payloads[
                "warnings"
            ],
        }

    @staticmethod
    def _filter_available_earnings(
        entries: list[dict[str, Any]],
        earning_codes: dict[str, str],
    ) -> tuple[
        list[dict[str, Any]],
        set[str],
        set[tuple[str, str]],
    ]:
        """Validate earnings and apply temporary fallbacks."""

        valid_entries: list[dict[str, Any]] = []
        skipped_codes: set[str] = set()
        temporary_mappings: set[
            tuple[str, str]
        ] = set()

        for entry in entries:
            requested_code = str(
                entry.get("earningCode")
                or ""
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

    @staticmethod
    def _validate_group_payload(
        payload: dict[str, Any],
        *,
        pay_group_id: str,
    ) -> None:
        """Validate a complete group before any submission begins."""

        process_id = str(
            payload.get("processId")
            or ""
        ).strip()
        employees = payload.get(
            "importEmployees"
        )

        if not process_id:
            raise PaycorTimesheetSyncServiceError(
                "Paycor process ID is required"
            )

        if not isinstance(employees, list) or not employees:
            raise PaycorTimesheetSyncServiceError(
                "Paycor payload must contain employees"
            )

        for employee in employees:
            if not isinstance(
                employee.get("employeeNumber"),
                int,
            ):
                raise PaycorTimesheetSyncServiceError(
                    "Paycor employee number must be numeric"
                )

            earnings = employee.get(
                "importEarnings"
            )

            if not isinstance(earnings, list) or not earnings:
                raise PaycorTimesheetSyncServiceError(
                    "Paycor employee must contain earnings"
                )

            for earning in earnings:
                if (
                    str(earning.get("payGroupId"))
                    != pay_group_id
                ):
                    raise PaycorTimesheetSyncServiceError(
                        "Paycor payload contains earnings "
                        "from another pay group"
                    )

                if not isinstance(
                    earning.get("departmentCode"),
                    int,
                ):
                    raise PaycorTimesheetSyncServiceError(
                        "Paycor department code must be "
                        "numeric"
                    )

                if not str(
                    earning.get("earningCode")
                    or ""
                ).strip():
                    raise PaycorTimesheetSyncServiceError(
                        "Paycor earning code is required"
                    )

                if Decimal(
                    str(earning.get("earningHours"))
                ) <= 0:
                    raise PaycorTimesheetSyncServiceError(
                        "Paycor earning hours must be "
                        "positive"
                    )
