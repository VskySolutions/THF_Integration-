import httpx

from app.features.schedular_services.constants import (
    SAP_CONCUR_ENGAGEMENTS_TASKS_SYNC_PATH,
)


async def run_sap_concur_engagements_tasks_sync(
    client: httpx.AsyncClient,
) -> bool:
    """Call the SAP Concur engagements and tasks sync endpoint."""
    try:
        response = await client.post(SAP_CONCUR_ENGAGEMENTS_TASKS_SYNC_PATH)
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True
