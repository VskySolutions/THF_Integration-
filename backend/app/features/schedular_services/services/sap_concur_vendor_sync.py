import httpx

from app.features.schedular_services.constants import (
    SAP_CONCUR_VENDOR_SYNC_PATH,
)


async def run_sap_concur_vendor_sync(client: httpx.AsyncClient) -> bool:
    try:
        response = await client.post(SAP_CONCUR_VENDOR_SYNC_PATH)
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True
