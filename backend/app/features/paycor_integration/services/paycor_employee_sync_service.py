"""Orchestrate Paycor employee creation in Maconomy."""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.paycor_integration.constants import (
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
        self.maconomy_service = (
            MaconomyEmployeeService()
        )

    async def sync_recent_hires(
        self,
        session: AsyncSession,
        
    ) -> list[dict[str, Any]]:
        """Synchronize recently hired Paycor employees."""


        try:
            raw_employees, departments = (
                await self.paycor_service
                .get_all_employee_data()
            )

        except PaycorServiceError as exc:
            raise PaycorEmployeeSyncServiceError(
                "Unable to retrieve employees from Paycor"
            ) from exc

        departments_by_id = (
            self._build_department_lookup(
                departments
            )
        )

        valid_hire_dates = (
            self._recent_hire_dates()
        )

        employees_to_process = [
            employee
            for employee in raw_employees
            if self._get_hire_date(employee)
            in valid_hire_dates
        ]

        

        if not employees_to_process:
            return []

        maconomy_employee_numbers = (
            await self
            ._load_maconomy_employee_numbers()
        )

        results: list[dict[str, Any]] = []

        for raw_employee in employees_to_process:
            try:
                employee = map_paycor_employee(
                    raw_employee,
                    departments_by_id=(
                        departments_by_id
                    ),
                )

            except Exception as exc:
                await session.rollback()

                message = str(exc)

                await (
                    self._save_unexpected_failure_log(
                        session,
                        raw_employee,
                        message,
                    )
                )

                results.append(
                    self._failure_result(
                        raw_employee,
                        message,
                    )
                )

                continue

            result = (
                await self._sync_mapped_employee(
                    session,
                    employee,
                    maconomy_employee_numbers=(
                        maconomy_employee_numbers
                    ),
                )
            )

            results.append(result)

        return results

    async def sync_employee_by_id(
        self,
        session: AsyncSession,
        *,
        paycor_employee_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Manually synchronize one Paycor employee."""

        try:
            employee = (
                await self.paycor_service
                .get_employee_by_id(
                    str(paycor_employee_id)
                )
            )

        except PaycorServiceError as exc:
            raise PaycorEmployeeSyncServiceError(
                "Unable to retrieve the employee "
                "from Paycor"
            ) from exc

        if employee is None:
            raise PaycorEmployeeSyncServiceError(
                "Paycor employee was not found"
            )

        maconomy_employee_numbers = (
            await self
            ._load_maconomy_employee_numbers()
        )

        return await self._sync_mapped_employee(
            session,
            employee,
            maconomy_employee_numbers=(
                maconomy_employee_numbers
            ),
        )

    async def _load_maconomy_employee_numbers(
        self,
    ) -> set[str]:
        """Load existing Maconomy employee numbers once."""

        try:
            return await (
                self.maconomy_service
                .get_all_employee_numbers()
            )

        except MaconomyEmployeeServiceError as exc:
            raise PaycorEmployeeSyncServiceError(
                "Unable to retrieve existing "
                "employees from Maconomy"
            ) from exc

    async def _sync_mapped_employee(
        self,
        session: AsyncSession,
        employee: dict[str, Any],
        *,
        maconomy_employee_numbers: set[str],
    ) -> dict[str, Any]:
        try:
            return await self._sync_one_employee(
                session,
                employee,
                maconomy_employee_numbers=(
                    maconomy_employee_numbers
                ),
            )

        except Exception as exc:
            await session.rollback()

            message = str(exc)

            await (
                self._save_unexpected_failure_log(
                    session,
                    employee,
                    message,
                )
            )

            return self._failure_result(
                employee,
                message,
            )

    async def _sync_one_employee(
        self,
        session: AsyncSession,
        employee: dict[str, Any],
        *,
        maconomy_employee_numbers: set[str],
    ) -> dict[str, Any]:
        paycor_employee_id = self._parse_uuid(
            employee.get("paycorEmployeeId"),
            "employee ID",
        )

        legal_entity_id = (
            self._parse_legal_entity_id(
                employee.get("legalEntityId")
            )
        )

        paycor_employee_number = (
            self._require_employee_number(
                employee.get("employeeNumber")
            )
        )

        mapping = (
            await employee_mapping_service
            .get_mapping_by_paycor_employee(
                session,
                legal_entity_id=legal_entity_id,
                paycor_employee_id=(
                    paycor_employee_id
                ),
            )
        )

        # Employee is already fully mapped.
        if (
            mapping is not None
            and mapping.maconomy_employee_number
        ):
            mapping_id = mapping.id

            mapped_paycor_number = (
                self._normalize_employee_number(
                    mapping.paycor_employee_number
                )
            )

            mapped_maconomy_number = (
                self._normalize_employee_number(
                    mapping.maconomy_employee_number
                )
            )

            if (
                mapped_paycor_number
                != paycor_employee_number
                or mapped_maconomy_number
                != paycor_employee_number
            ):
                message = (
                    "Existing mapping has different "
                    "employee numbers; manual "
                    "reconciliation is required"
                )

                await self._write_log(
                    session,
                    mapping_id=mapping_id,
                    paycor_employee_id=(
                        paycor_employee_id
                    ),
                    paycor_employee_number=(
                        paycor_employee_number
                    ),
                    legal_entity_id=legal_entity_id,
                    status=IntegrationStatus.FAILED,
                    message=message,
                )

                return self._result(
                    paycor_employee_id,
                    paycor_employee_number,
                    "FAILED",
                    mapped_maconomy_number,
                    message,
                )
            
            if (
                mapped_maconomy_number
                not in maconomy_employee_numbers
                ):
                message = (
                    "Employee mapping exists, but the "
                    "Maconomy employee was not found; "
                    "manual reconciliation is required"
                )

                await self._write_log(
                    session,
                    mapping_id=mapping.id,
                    paycor_employee_id=(
                        paycor_employee_id
                    ),
                    paycor_employee_number=(
                        paycor_employee_number
                    ),
                    legal_entity_id=legal_entity_id,
                    status=IntegrationStatus.FAILED,
                    message=message,
                )

                return self._result(
                    paycor_employee_id,
                    paycor_employee_number,
                    "FAILED",
                    mapped_maconomy_number,
                    message,
                )

            message = (
                "Employee already mapped; "
                "creation skipped"
            )

            await self._write_log(
                session,
                mapping_id=mapping_id,
                paycor_employee_id=(
                    paycor_employee_id
                ),
                paycor_employee_number=(
                    paycor_employee_number
                ),
                legal_entity_id=legal_entity_id,
                status=IntegrationStatus.SUCCESS,
                message=message,
            )

            return self._result(
                paycor_employee_id,
                paycor_employee_number,
                "SKIPPED",
                mapped_maconomy_number,
                message,
            )

        # Employee already exists in Maconomy, but
        # its mapping is absent or incomplete.
        if (
            paycor_employee_number
            in maconomy_employee_numbers
        ):
            if mapping is None:
                (
                    mapping,
                    _,
                ) = await (
                    employee_mapping_service
                    .create_pending_mapping(
                        session,
                        legal_entity_id=(
                            legal_entity_id
                        ),
                        paycor_employee_id=(
                            paycor_employee_id
                        ),
                        paycor_employee_number=(
                            paycor_employee_number
                        ),
                    )
                )

            mapping_id = mapping.id

            existing_paycor_number = (
                self._normalize_employee_number(
                    mapping.paycor_employee_number
                )
            )

            existing_maconomy_number = (
                self._normalize_employee_number(
                    mapping.maconomy_employee_number
                )
            )

            has_conflicting_mapping = (
                existing_paycor_number is not None
                and existing_paycor_number
                != paycor_employee_number
            ) or (
                existing_maconomy_number is not None
                and existing_maconomy_number
                != paycor_employee_number
            )

            if has_conflicting_mapping:
                message = (
                    "Existing mapping has different "
                    "employee numbers; manual "
                    "reconciliation is required"
                )

                await self._write_log(
                    session,
                    mapping_id=mapping_id,
                    paycor_employee_id=(
                        paycor_employee_id
                    ),
                    paycor_employee_number=(
                        paycor_employee_number
                    ),
                    legal_entity_id=legal_entity_id,
                    status=IntegrationStatus.FAILED,
                    message=message,
                )

                return self._result(
                    paycor_employee_id,
                    paycor_employee_number,
                    "FAILED",
                    existing_maconomy_number,
                    message,
                )

            await (
                employee_mapping_service
                .complete_mapping(
                    session,
                    mapping,
                    paycor_employee_number=(
                        paycor_employee_number
                    ),
                    maconomy_employee_number=(
                        paycor_employee_number
                    ),
                )
            )

            message = (
                "Employee already exists in Maconomy; "
                "mapping reconciled and creation skipped"
            )

            await self._write_log(
                session,
                mapping_id=mapping_id,
                paycor_employee_id=(
                    paycor_employee_id
                ),
                paycor_employee_number=(
                    paycor_employee_number
                ),
                legal_entity_id=legal_entity_id,
                status=IntegrationStatus.SUCCESS,
                message=message,
            )

            return self._result(
                paycor_employee_id,
                paycor_employee_number,
                "SKIPPED",
                paycor_employee_number,
                message,
            )

        # Reuse a pending mapping from an earlier
        # failed attempt when Maconomy confirms that
        # the employee does not exist.
        if mapping is not None:
            mapping_id = mapping.id

            existing_paycor_number = (
                self._normalize_employee_number(
                    mapping.paycor_employee_number
                )
            )

            if (
                existing_paycor_number
                != paycor_employee_number
            ):
                message = (
                    "Pending mapping has a different "
                    "Paycor employee number; manual "
                    "reconciliation is required"
                )

                await self._write_log(
                    session,
                    mapping_id=mapping_id,
                    paycor_employee_id=(
                        paycor_employee_id
                    ),
                    paycor_employee_number=(
                        paycor_employee_number
                    ),
                    legal_entity_id=legal_entity_id,
                    status=IntegrationStatus.FAILED,
                    message=message,
                )

                return self._result(
                    paycor_employee_id,
                    paycor_employee_number,
                    "FAILED",
                    None,
                    message,
                )

        else:
            (
                mapping,
                mapping_was_created,
            ) = await (
                employee_mapping_service
                .create_pending_mapping(
                    session,
                    legal_entity_id=legal_entity_id,
                    paycor_employee_id=(
                        paycor_employee_id
                    ),
                    paycor_employee_number=(
                        paycor_employee_number
                    ),
                )
            )

            mapping_id = mapping.id

            if not mapping_was_created:
                mapped_paycor_number = (
                    self._normalize_employee_number(
                        mapping.paycor_employee_number
                    )
                )

                mapped_maconomy_number = (
                    self._normalize_employee_number(
                        mapping.maconomy_employee_number
                    )
                )

                if mapped_maconomy_number is not None:
                    if (
                        mapped_paycor_number
                        != paycor_employee_number
                        or mapped_maconomy_number
                        != paycor_employee_number
                    ):
                        message = (
                            "Employee was mapped by another "
                            "synchronization run with "
                            "different employee numbers; "
                            "manual reconciliation is required"
                        )

                        await self._write_log(
                            session,
                            mapping_id=mapping_id,
                            paycor_employee_id=(
                                paycor_employee_id
                            ),
                            paycor_employee_number=(
                                paycor_employee_number
                            ),
                            legal_entity_id=(
                                legal_entity_id
                            ),
                            status=(
                                IntegrationStatus.FAILED
                            ),
                            message=message,
                        )

                        return self._result(
                            paycor_employee_id,
                            paycor_employee_number,
                            "FAILED",
                            mapped_maconomy_number,
                            message,
                        )

                    message = (
                        "Employee was mapped by another "
                        "synchronization run; "
                        "creation skipped"
                    )

                    await self._write_log(
                        session,
                        mapping_id=mapping_id,
                        paycor_employee_id=(
                            paycor_employee_id
                        ),
                        paycor_employee_number=(
                            paycor_employee_number
                        ),
                        legal_entity_id=legal_entity_id,
                        status=(
                            IntegrationStatus.SUCCESS
                        ),
                        message=message,
                    )

                    return self._result(
                        paycor_employee_id,
                        paycor_employee_number,
                        "SKIPPED",
                        mapped_maconomy_number,
                        message,
                    )

                message = (
                    "Another synchronization run has "
                    "a pending mapping; creation skipped"
                )

                await self._write_log(
                    session,
                    mapping_id=mapping_id,
                    paycor_employee_id=(
                        paycor_employee_id
                    ),
                    paycor_employee_number=(
                        paycor_employee_number
                    ),
                    legal_entity_id=legal_entity_id,
                    status=IntegrationStatus.FAILED,
                    message=message,
                )

                return self._result(
                    paycor_employee_id,
                    paycor_employee_number,
                    "FAILED",
                    None,
                    message,
                )

        mapping_id = mapping.id

        # Keep Paycor manager data in the normalized
        # record, but omit it from creation when the
        # manager does not exist in Maconomy.
        employee_to_create = dict(employee)

        manager_employee_number = (
            self._normalize_employee_number(
                employee.get(
                    "managerEmployeeNumber"
                )
            )
        )

        skipped_manager_employee_number: (
            str | None
        ) = None

        if (
            manager_employee_number is not None
            and manager_employee_number
            not in maconomy_employee_numbers
        ):
            employee_to_create[
                "managerEmployeeNumber"
            ] = None

            skipped_manager_employee_number = (
                manager_employee_number
            )

        try:
            created_employee = await (
                self.maconomy_service
                .create_employee(
                    employee_to_create
                )
            )

            maconomy_employee_number = (
                self._get_maconomy_number(
                    created_employee
                )
            )

            # Update the in-memory collection so another
            # record in the same run cannot recreate it.
            maconomy_employee_numbers.add(
                maconomy_employee_number
            )

            if (
                maconomy_employee_number
                != paycor_employee_number
            ):
                raise ValueError(
                    "Maconomy returned a different "
                    "employee number than the Paycor "
                    "employee number"
                )

            await (
                employee_mapping_service
                .complete_mapping(
                    session,
                    mapping,
                    paycor_employee_number=(
                        paycor_employee_number
                    ),
                    maconomy_employee_number=(
                        maconomy_employee_number
                    ),
                )
            )

        except (
            MaconomyEmployeeServiceError,
            ValueError,
        ) as exc:
            await session.rollback()

            message = str(exc)

            await self._write_log(
                session,
                mapping_id=mapping_id,
                paycor_employee_id=(
                    paycor_employee_id
                ),
                paycor_employee_number=(
                    paycor_employee_number
                ),
                legal_entity_id=legal_entity_id,
                status=IntegrationStatus.FAILED,
                message=message,
            )

            return self._result(
                paycor_employee_id,
                paycor_employee_number,
                "FAILED",
                None,
                message,
            )

        if (
            skipped_manager_employee_number
            is not None
        ):
            message = (
                "Maconomy employee created and mapping "
                "saved; superior employee "
                f"{skipped_manager_employee_number} was "
                "not assigned because it does not exist "
                "in Maconomy"
            )

        else:
            message = (
                "Maconomy employee created "
                "and mapping saved"
            )

        await self._write_log(
            session,
            mapping_id=mapping_id,
            paycor_employee_id=(
                paycor_employee_id
            ),
            paycor_employee_number=(
                paycor_employee_number
            ),
            legal_entity_id=legal_entity_id,
            status=IntegrationStatus.SUCCESS,
            message=message,
        )

        return self._result(
            paycor_employee_id,
            paycor_employee_number,
            "CREATED",
            maconomy_employee_number,
            message,
        )

    @staticmethod
    async def _write_log(
        session: AsyncSession,
        *,
        mapping_id: uuid.UUID | None,
        paycor_employee_id: uuid.UUID,
        paycor_employee_number: str | None,
        legal_entity_id: int,
        status: IntegrationStatus,
        message: str,
    ) -> None:
        await integration_log_service.create_log(
            session,
            mapping_id=mapping_id,
            paycor_employee_id=(
                paycor_employee_id
            ),
            paycor_employee_number=(
                paycor_employee_number
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
        employee_id_value =  employee.get(
            "paycorEmployeeId"
        )

        if employee_id_value is None:
            employee_id_value = employee.get(
                "id"
            )

        legal_entity_value = employee.get(
            "legalEntityId"
        )

        if legal_entity_value is None:
            legal_entity_data = employee.get(
                "legalEntity"
            )

            if isinstance(
                legal_entity_data,
                dict,
            ):
                legal_entity_value = (
                    legal_entity_data.get("id")
                )

        employee_number = (
            PaycorEmployeeSyncService
            ._normalize_employee_number(
                employee.get("employeeNumber")
            )
        )

        try:
            paycor_employee_id = uuid.UUID(
                str(employee_id_value)
            )

            if isinstance(
                legal_entity_value,
                bool,
            ):
                return

            legal_entity_id = int(
                str(legal_entity_value).strip()
            )

            if legal_entity_id <= 0:
                return

        except (
            AttributeError,
            TypeError,
            ValueError,
        ):
            return

        try:
            mapping = (
                await employee_mapping_service
                .get_mapping_by_paycor_employee(
                    session,
                    legal_entity_id=(
                        legal_entity_id
                    ),
                    paycor_employee_id=(
                        paycor_employee_id
                    ),
                )
            )

            mapping_id = (
                mapping.id
                if mapping is not None
                else None
            )

            await integration_log_service.create_log(
                session,
                mapping_id=mapping_id,
                paycor_employee_id=(
                    paycor_employee_id
                ),
                paycor_employee_number=(
                    employee_number
                ),
                legal_entity_id=legal_entity_id,
                status=IntegrationStatus.FAILED,
                action=IntegrationAction.CREATE,
                message=message,
            )

        except Exception:
            await session.rollback()

    @staticmethod
    def _build_department_lookup(
        departments: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
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
    def _get_hire_date(
        employee: dict[str, Any],
    ) -> date | None:
        employment_date_data = employee.get(
            "employmentDateData"
        )

        if not isinstance(
            employment_date_data,
            dict,
        ):
            return None

        hire_date_value = (
            employment_date_data.get(
                "hireDate"
            )
        )

        if not isinstance(
            hire_date_value,
            str,
        ):
            return None

        try:
            return date.fromisoformat(
                hire_date_value.strip()[:10]
            )

        except ValueError:
            return None

    @staticmethod
    def _recent_hire_dates() -> set[date]:
        today = (
            datetime.now(timezone.utc).date()
        )

        return {
            today,
            today - timedelta(days=1),
        }

    

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
                f"Paycor {field_name} must "
                "be a valid UUID"
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
                "Paycor legal entity ID "
                "must be an integer"
            )

        return value

    @staticmethod
    def _normalize_employee_number(
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        normalized_value = str(value).strip()

        return normalized_value or None

    @classmethod
    def _require_employee_number(
        cls,
        value: Any,
    ) -> str:
        employee_number = (
            cls._normalize_employee_number(value)
        )

        if employee_number is None:
            raise PaycorEmployeeSyncServiceError(
                "Paycor employee number is required"
            )

        return employee_number

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
                "Maconomy did not return "
                "an employee number"
            )

        return str(value).strip()

    @staticmethod
    def _result(
        paycor_employee_id: uuid.UUID,
        paycor_employee_number: str,
        status: str,
        maconomy_employee_number: str | None,
        message: str,
    ) -> dict[str, Any]:
        return {
            "paycorEmployeeId": str(
                paycor_employee_id
            ),
            "paycorEmployeeNumber": (
                paycor_employee_number
            ),
            "status": status,
            "maconomyEmployeeNumber": (
                maconomy_employee_number
            ),
            "message": message,
        }

    @staticmethod
    def _failure_result(
        employee: dict[str, Any],
        message: str,
    ) -> dict[str, Any]:
        paycor_employee_id = employee.get(
            "paycorEmployeeId"
        )

        if paycor_employee_id is None:
            paycor_employee_id = employee.get(
                "id"
            )

        return {
            "paycorEmployeeId": (
                paycor_employee_id
            ),
            "paycorEmployeeNumber": (
                employee.get("employeeNumber")
            ),
            "status": "FAILED",
            "maconomyEmployeeNumber": None,
            "message": message,
        }