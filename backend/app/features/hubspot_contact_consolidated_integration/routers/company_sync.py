import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.hubspot_contact_consolidated_integration.services.sync_orchestrator import (
    ConsolidatedSyncService,
)
from app.features.integration_services import (
    IntegrationServiceIdentifier,
    require_active_integration_service,
)

router = APIRouter(
    prefix="/hubspot-consolidated",
    tags=["hubspot-consolidated-integration"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/companies/{maconomy_customer_number}/sync",
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_HUBSPOT_CONTACT_CONSOLIDATED_SYNC
            )
        )
    ],
)
async def sync_company_by_customer_number(
    maconomy_customer_number: str,
    request: Request,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Force-sync one Maconomy Customer into a HubSpot Company."""
    request_id = getattr(request.state, "request_id", uuid.uuid4())
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.UUID(str(request_id))
    service = ConsolidatedSyncService(session)
    return await service.run_company_manual(
        request_id,
        maconomy_customer_number,
    )
