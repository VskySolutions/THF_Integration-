from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.integration_services.constants import IntegrationServiceIdentifier
from app.features.integration_services.exceptions import (
    IntegrationServiceInactiveError,
    IntegrationServiceNotConfiguredError,
)
from app.features.integration_services.models import IntegrationService


async def get_active_service(
    session: AsyncSession,
    identifier: IntegrationServiceIdentifier,
) -> IntegrationService:
    result = await session.execute(
        select(IntegrationService).where(
            IntegrationService.identifier_unique_name == identifier.value,
            IntegrationService.is_deleted.is_(False),
        )
    )
    integration_service = result.scalar_one_or_none()

    if integration_service is None:
        raise IntegrationServiceNotConfiguredError(identifier)
    if not integration_service.is_active:
        raise IntegrationServiceInactiveError(identifier)

    return integration_service
