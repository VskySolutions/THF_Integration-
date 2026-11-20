"""Entry point for the new consolidated HubSpot batch flow."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.hubspot_contact_consolidated_integration_v1.services.sync_orchestrator import (
    ConsolidatedSyncService,
)
from app.features.integration_services import (
    IntegrationServiceIdentifier,
    require_active_integration_service,
)

router = APIRouter(
    prefix="/hubspot-consolidated",
    tags=["hubspot-consolidated-integration-v1"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


def _trigger_type(request: Request) -> str:
    header = request.headers.get("X-Integration-Trigger", "API").upper()
    return "SCHEDULER" if header == "SCHEDULER" else "API"


@router.post(
    "/sync/customers",
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_HUBSPOT_CONTACT_CONSOLIDATED_SYNC
            )
        )
    ],
)
async def sync_customers_consolidated_v1(
    request: Request,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Run the new batch flow once its steps are implemented."""
    request_id = getattr(request.state, "request_id", uuid.uuid4())
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.UUID(str(request_id))
    service = ConsolidatedSyncService(session)
    return await service.run_bulk(request_id, _trigger_type(request))
