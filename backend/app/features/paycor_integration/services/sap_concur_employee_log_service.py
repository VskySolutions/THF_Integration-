"""Service for recording and managing SAP Concur employee creation status and logs."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.paycor_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
    SAPConcurUserCreationStatus,
)
from app.features.paycor_integration.models.employee_mapping_log import (
    PaycorEmployeeMappingLog,
)
from app.features.paycor_integration.models.integration_log import (
    PaycorIntegrationLog,
)


class SAPConcurEmployeeLogService:
    @staticmethod
    async def record_sap_concur_result(
        session: AsyncSession,
        *,
        mapping: PaycorEmployeeMappingLog,
        paycor_employee_id: uuid.UUID,
        paycor_employee_number: str | None,
        legal_entity_id: int,
        status: SAPConcurUserCreationStatus,
        sap_concur_user_id: str | None = None,
        error_message: str | None = None,
    ) -> PaycorIntegrationLog | None:
        """Update mapping log record and create an audit integration log for SAP Concur."""
        mapping.is_sap_concur_created = status
        if sap_concur_user_id:
            mapping.sap_concur_user_id = str(sap_concur_user_id).strip()

        settings = get_settings()

        integration_status = (
            IntegrationStatus.SUCCESS
            if status == SAPConcurUserCreationStatus.SUCCESS
            else IntegrationStatus.FAILED
        )

        message = (
            f"SAP Concur user created successfully (ID: {sap_concur_user_id})"
            if status == SAPConcurUserCreationStatus.SUCCESS
            else (error_message or "SAP Concur user creation failed")
        )

        log_entry = PaycorIntegrationLog(
            paycor_employee_mapping_log_id=mapping.id,
            paycor_employee_id=paycor_employee_id,
            paycor_employee_number=paycor_employee_number,
            instance=str(legal_entity_id),
            base_url=settings.sap_concur_api_base_url,
            status=integration_status,
            action=IntegrationAction.CREATE,
            message=message,
        )

        session.add(log_entry)
        await session.flush()
        return log_entry
