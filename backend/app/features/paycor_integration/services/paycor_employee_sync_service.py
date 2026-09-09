"""Orchestrate Paycor employee creation in Maconomy."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.paycor_integration.constants import (
    EmployeeStatus,
    IntegrationAction,
    IntegrationStatus,
)
from app.features.paycor_integration.mappers import (
    map_paycor_employee,
)
from app.features.paycor_integration.services import (
    employee_mapping_service,
    integration_log_service,
)
from app.features.paycor_integration.services.maconomy_employee_service import (
    MaconomyEmployeeService,
    MaconomyEmployeeServiceError,
)
from app.features.paycor_integration.services.paycor_employee_service import (
    PaycorService,
    PaycorServiceError,
)


class PaycorEmployeeSyncServiceError(Exception):
    """Raised when Paycor synchronization cannot start."""


class PaycorEmployeeSyncService:
    def __init__(self) -> None:
        self.paycor_service = PaycorService()
        self.maconomy_service = MaconomyEmployeeService()

    async def sync_onboarding_employees(
        self,
        session: AsyncSession,
        *,
        max_records: int = 2,
    ) -> list[dict[str, Any]]:
        raw_employees, work_locations = (
        await self.paycor_service.get_all_onboarding_data()
    )

    # Paycor has returned all employees, but only this
    # small group will be processed during testing.
        employees_to_process = raw_employees[:max_records]

        results: list[dict[str, Any]] = []

        for raw_employee in employees_to_process:
            try:
                employee = map_paycor_employee(
                    raw_employee,
                    work_locations=work_locations,
                )

                result = await self._sync_one_employee(
                session,
                employee,
            )

                results.append(result)

            except Exception as exc:
                await session.rollback()

                results.append(
                    {
                        "onboardingEmployeeId": (
                            raw_employee.get(
                            "onboardingEmployeeId"
                        )
                    ),
                        "status": "FAILED",
                        "message": str(exc),
                }
            )

        return results

    async def _sync_one_employee(
        self,
        session: AsyncSession,
        employee: dict[str, Any],
    ) -> dict[str, Any]:
        onboarding_employee_id = self._parse_uuid(
            employee.get("onboardingEmployeeId"),
            "onboardingEmployeeId",
        )

        legal_entity_id = self._parse_legal_entity_id(
            employee.get("legalEntityId")
        )

        employee_status = self._parse_employee_status(
            employee.get("employeeStatus")
        )

        paycor_employee_number = (
            self._normalize_employee_number(
                employee.get("employeeNumber")
            )
        )

        mapping = (
            await employee_mapping_service
            .get_mapping_by_paycor_employee(
                session,
                legal_entity_id=legal_entity_id,
                onboarding_employee_id=(
                    onboarding_employee_id
                ),
            )
        )

        if (
            mapping is not None
            and mapping.maconomy_employee_number
        ):
            await employee_mapping_service.update_mapping(
                session,
                mapping,
                paycor_employee_number=(
                    paycor_employee_number
                ),
                employee_status=employee_status,
            )

            message = (
                "Employee already mapped; creation skipped"
            )

            await self._write_log(
                session,
                mapping_id=mapping.id,
                onboarding_employee_id=(
                    onboarding_employee_id
                ),
                legal_entity_id=legal_entity_id,
                status=IntegrationStatus.SUCCESS,
                message=message,
            )

            return self._result(
                onboarding_employee_id,
                "SKIPPED",
                mapping.maconomy_employee_number,
                message,
            )

        if mapping is not None:
            message = (
                "Mapping exists without a Maconomy employee "
                "number; manual reconciliation is required"
            )

            await self._write_log(
                session,
                mapping_id=mapping.id,
                onboarding_employee_id=(
                    onboarding_employee_id
                ),
                legal_entity_id=legal_entity_id,
                status=IntegrationStatus.FAILED,
                message=message,
            )

            return self._result(
                onboarding_employee_id,
                "FAILED",
                None,
                message,
            )

        (
            mapping,
            mapping_was_created,
        ) = await (
            employee_mapping_service
            .create_pending_mapping(
                session,
                legal_entity_id=legal_entity_id,
                onboarding_employee_id=(
                    onboarding_employee_id
                ),
                paycor_employee_number=(
                    paycor_employee_number
                ),
                employee_status=employee_status,
            )
        )

        if not mapping_was_created:
            if mapping.maconomy_employee_number:
                message = (
                    "Employee was mapped by another "
                    "synchronization run; creation skipped"
                )

                await self._write_log(
                    session,
                    mapping_id=mapping.id,
                    onboarding_employee_id=(
                        onboarding_employee_id
                    ),
                    legal_entity_id=legal_entity_id,
                    status=IntegrationStatus.SUCCESS,
                    message=message,
                )

                return self._result(
                    onboarding_employee_id,
                    "SKIPPED",
                    mapping.maconomy_employee_number,
                    message,
                )

            message = (
                "Another synchronization run created a "
                "pending mapping; creation skipped"
            )

            await self._write_log(
                session,
                mapping_id=mapping.id,
                onboarding_employee_id=(
                    onboarding_employee_id
                ),
                legal_entity_id=legal_entity_id,
                status=IntegrationStatus.FAILED,
                message=message,
            )

            return self._result(
                onboarding_employee_id,
                "FAILED",
                None,
                message,
            )

        try:
            created_employee = (
                await self.maconomy_service
                .create_employee(employee)
            )

            maconomy_employee_number = (
                self._get_maconomy_number(
                    created_employee
                )
            )

            await employee_mapping_service.complete_mapping(
                session,
                mapping,
                paycor_employee_number=(
                    paycor_employee_number
                ),
                maconomy_employee_number=(
                    maconomy_employee_number
                ),
                employee_status=employee_status,
            )

        except (
            MaconomyEmployeeServiceError,
            ValueError,
        ) as exc:
            await session.rollback()

            message = str(exc)

            await self._write_log(
                session,
                mapping_id=mapping.id,
                onboarding_employee_id=(
                    onboarding_employee_id
                ),
                legal_entity_id=legal_entity_id,
                status=IntegrationStatus.FAILED,
                message=message,
            )

            return self._result(
                onboarding_employee_id,
                "FAILED",
                None,
                message,
            )

        message = (
            "Maconomy employee created and mapping saved"
        )

        await self._write_log(
            session,
            mapping_id=mapping.id,
            onboarding_employee_id=(
                onboarding_employee_id
            ),
            legal_entity_id=legal_entity_id,
            status=IntegrationStatus.SUCCESS,
            message=message,
        )

        return self._result(
            onboarding_employee_id,
            "CREATED",
            maconomy_employee_number,
            message,
        )

    @staticmethod
    async def _write_log(
        session: AsyncSession,
        *,
        mapping_id: uuid.UUID | None,
        onboarding_employee_id: uuid.UUID,
        legal_entity_id: int,
        status: IntegrationStatus,
        message: str,
    ) -> None:
        await integration_log_service.create_log(
            session,
            mapping_id=mapping_id,
            onboarding_employee_id=(
                onboarding_employee_id
            ),
            legal_entity_id=legal_entity_id,
            status=status,
            action=IntegrationAction.CREATE,
            message=message,
        )

    @staticmethod
    async def _save_unexpected_failure_log(
        session: AsyncSession,
        employee: dict[str, Any],
        message: str,
    ) -> None:
        onboarding_id_value = employee.get(
            "onboardingEmployeeId"
        )
        legal_entity_id = employee.get(
            "legalEntityId"
        )

        try:
            onboarding_employee_id = uuid.UUID(
                str(onboarding_id_value)
            )

        except (
            AttributeError,
            TypeError,
            ValueError,
        ):
            return

        if (
            not isinstance(legal_entity_id, int)
            or isinstance(legal_entity_id, bool)
        ):
            return

        try:
            mapping = (
                await employee_mapping_service
                .get_mapping_by_paycor_employee(
                    session,
                    legal_entity_id=legal_entity_id,
                    onboarding_employee_id=(
                        onboarding_employee_id
                    ),
                )
            )

            await integration_log_service.create_log(
                session,
                mapping_id=(
                    mapping.id
                    if mapping is not None
                    else None
                ),
                onboarding_employee_id=(
                    onboarding_employee_id
                ),
                legal_entity_id=legal_entity_id,
                status=IntegrationStatus.FAILED,
                action=IntegrationAction.CREATE,
                message=message,
            )

        except Exception:
            await session.rollback()

    @staticmethod
    def _parse_uuid(
        value: Any,
        field_name: str,
    ) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))

        except (
            AttributeError,
            TypeError,
            ValueError,
        ) as exc:
            raise PaycorEmployeeSyncServiceError(
                f"Paycor {field_name} must be a valid UUID"
            ) from exc

    @staticmethod
    def _parse_legal_entity_id(
        value: Any,
    ) -> int:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
        ):
            raise PaycorEmployeeSyncServiceError(
                "Paycor legal entity ID must be an integer"
            )

        return value

    @staticmethod
    def _parse_employee_status(
        value: Any,
    ) -> EmployeeStatus:
        if isinstance(value, EmployeeStatus):
            return value

        try:
            return EmployeeStatus(value)

        except (TypeError, ValueError):
            try:
                return EmployeeStatus[
                    str(value).upper()
                ]

            except (
                KeyError,
                TypeError,
                ValueError,
            ) as exc:
                raise PaycorEmployeeSyncServiceError(
                    "Paycor employee status is invalid"
                ) from exc

    @staticmethod
    def _normalize_employee_number(
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        normalized_value = str(value).strip()

        return normalized_value or None

    @staticmethod
    def _get_maconomy_number(
        employee: dict[str, Any],
    ) -> str:
        value = employee.get("employeenumber")

        if (
            value is None
            or not str(value).strip()
        ):
            raise ValueError(
                "Maconomy did not return an employee number"
            )

        return str(value).strip()

    @staticmethod
    def _result(
        onboarding_employee_id: uuid.UUID,
        status: str,
        maconomy_employee_number: str | None,
        message: str,
    ) -> dict[str, Any]:
        return {
            "onboardingEmployeeId": str(
                onboarding_employee_id
            ),
            "status": status,
            "maconomyEmployeeNumber": (
                maconomy_employee_number
            ),
            "message": message,
        }