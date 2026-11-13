"""Service for recording and managing Purpose creation status and logs."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.paycor_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
    PurposeCreationStatus,
)
from app.features.paycor_integration.models.employee_mapping_log import (
    PaycorEmployeeMappingLog,
)
from app.features.paycor_integration.models.integration_log import (
    PaycorIntegrationLog,
)


class PurposeLogService:
    @staticmethod
    async def record_purpose_result(
        session: AsyncSession,
        *,
        mapping: PaycorEmployeeMappingLog,
        paycor_employee_id: uuid.UUID,
        paycor_employee_number: str | None,
        legal_entity_id: int,
        status: PurposeCreationStatus,
        purpose_name: str | None = None,
        error_message: str | None = None,
    ) -> PaycorIntegrationLog | None:
        """Update mapping log record and create an audit integration log for Purpose."""
        mapping.is_purpose_created = status
        if purpose_name:
            mapping.maconomy_purpose_name = purpose_name

        settings = get_settings()

        integration_status = (
            IntegrationStatus.SUCCESS
            if status == PurposeCreationStatus.SUCCESS
            else IntegrationStatus.FAILED
        )

        message = (
            f"Purpose '{purpose_name}' created successfully"
            if status == PurposeCreationStatus.SUCCESS
            else (error_message or "Purpose creation failed")
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

