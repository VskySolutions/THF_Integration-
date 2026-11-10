"""Service for recording and managing Specification 5 creation status and logs."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.paycor_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
    Spec5CreationStatus,
)
from app.features.paycor_integration.models.employee_mapping_log import (
    PaycorEmployeeMappingLog,
)
from app.features.paycor_integration.models.integration_log import (
    PaycorIntegrationLog,
)


class Specification5LogService:
    @staticmethod
    async def record_specification5_result(
        session: AsyncSession,
        *,
        mapping: PaycorEmployeeMappingLog,
        paycor_employee_id: uuid.UUID,
        paycor_employee_number: str | None,
        legal_entity_id: int,
        status: Spec5CreationStatus,
        spec5_name: str | None = None,
        error_message: str | None = None,
    ) -> PaycorIntegrationLog | None:
        """Update mapping log record and create an audit integration log for Specification 5."""
        mapping.is_spec5_created = status
        if spec5_name:
            mapping.maconomy_spec5_name = spec5_name

        settings = get_settings()

        integration_status = (
            IntegrationStatus.SUCCESS
            if status == Spec5CreationStatus.SUCCESS
            else IntegrationStatus.FAILED
        )

        message = (
            f"Specification 5 '{spec5_name}' created successfully"
            if status == Spec5CreationStatus.SUCCESS
            else (error_message or "Specification 5 creation failed")
        )

        log_entry = PaycorIntegrationLog(
            paycor_employee_mapping_log_id=mapping.id,
            paycor_employee_id=paycor_employee_id,
            paycor_employee_number=paycor_employee_number,
            instance=str(legal_entity_id),
            base_url=settings.maconomy_url,
            status=integration_status,
            action=IntegrationAction.CREATE,
            message=message,
        )

        session.add(log_entry)
        await session.flush()
        return log_entry

