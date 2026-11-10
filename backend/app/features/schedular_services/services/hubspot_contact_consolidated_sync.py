import httpx

from app.features.schedular_services.constants import (
    HUBSPOT_CONTACT_CONSOLIDATED_SYNC_PATH,
)


async def run_hubspot_contact_consolidated_sync(
    client: httpx.AsyncClient,
) -> bool:
    """Call the scheduled consolidated Maconomy-to-HubSpot sync endpoint."""
    try:
        response = await client.post(
            HUBSPOT_CONTACT_CONSOLIDATED_SYNC_PATH,
            headers={"X-Integration-Trigger": "SCHEDULER"},
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True
