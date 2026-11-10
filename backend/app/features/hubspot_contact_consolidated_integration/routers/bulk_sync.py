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
async def sync_customers_consolidated(
    request: Request,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Synchronize changed Maconomy Customers and Contacts to HubSpot.

    Consolidated flow: parallel discovery, email de-duplication with one
    MASTER contact person per email group (remark4 routing), and
    one-MASTER-to-many-companies associations."""
    request_id = getattr(request.state, "request_id", uuid.uuid4())
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.UUID(str(request_id))
    trigger_type = _trigger_type(request)
    service = ConsolidatedSyncService(session)
    return await service.run_bulk(request_id, trigger_type)
