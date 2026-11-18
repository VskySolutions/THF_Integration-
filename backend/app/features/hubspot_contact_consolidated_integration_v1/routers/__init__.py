"""Routes for the new integration flow."""

from app.features.hubspot_contact_consolidated_integration_v1.routers.bulk_sync import (
    router as consolidated_bulk_sync_v1_router,
)
from app.features.hubspot_contact_consolidated_integration_v1.routers.company_sync import (
    router as consolidated_company_sync_v1_router,
)
from app.features.hubspot_contact_consolidated_integration_v1.routers.contact_sync import (
    router as consolidated_contact_sync_v1_router,
)

__all__ = [
    "consolidated_bulk_sync_v1_router",
    "consolidated_company_sync_v1_router",
    "consolidated_contact_sync_v1_router",
]
