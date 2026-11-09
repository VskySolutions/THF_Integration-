"""Database audit operations for Paycor Payroll integration execution logs."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.features.paycor_payroll_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)
from app.features.paycor_payroll_integration.models.integration_log import (
    PaycorPayrollIntegrationLog,
)
from app.features.paycor_payroll_integration.models.payroll_journal_mapping_log import (
    PaycorPayrollJournalMappingLog,
)


async def create_integration_log(
    session: AsyncSession,
    settings: Settings,
    *,
    status: IntegrationStatus,
    action: IntegrationAction,
    message: str | None = None,
    paycor_planner_id: str | None = None,
    department: str | None = None,
    journal_mapping_log: PaycorPayrollJournalMappingLog | None = None,
) -> PaycorPayrollIntegrationLog:
    """Persist an audit log entry for a payroll synchronization event."""
    log_entry = PaycorPayrollIntegrationLog(
        paycor_payroll_journal_mapping_log_id=(
            journal_mapping_log.id if journal_mapping_log else None
        ),
        paycor_planner_id=paycor_planner_id,
        department=department,
        instance=settings.app_env,
        base_url=settings.maconomy_url,
        status=status,
        action=action,
        message=message,
    )

    session.add(log_entry)
    await session.commit()
    await session.refresh(log_entry)
    return log_entry

