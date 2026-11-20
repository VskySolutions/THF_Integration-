"""Entry point for retrying one Company and its Contact Persons."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.hubspot_contact_consolidated_integration_v1.services.company_retry_service import (
    CompanyRetryService,
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
async def sync_company_by_customer_number_v1(
    maconomy_customer_number: str,
    request: Request,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Force one Customer and its Contact Persons through the v1 flow."""
    request_id = getattr(request.state, "request_id", uuid.uuid4())
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.UUID(str(request_id))
    return await CompanyRetryService(session).run(request_id, maconomy_customer_number)
