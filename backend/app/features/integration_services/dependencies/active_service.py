from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.integration_services.constants import IntegrationServiceIdentifier
from app.features.integration_services.models import IntegrationService
from app.features.integration_services.services import get_active_service

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
IntegrationServiceDependency = Callable[
    [AsyncSession],
    Coroutine[Any, Any, IntegrationService],
]


def require_active_integration_service(
    identifier: IntegrationServiceIdentifier,
) -> IntegrationServiceDependency:
    async def dependency(session: DatabaseSession) -> IntegrationService:
        return await get_active_service(session, identifier)

    return dependency
