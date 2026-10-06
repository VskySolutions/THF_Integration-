import httpx

from app.features.schedular_services.constants import (
    PAYCOR_CREATE_SYNC_PATH,
    PAYCOR_UPDATE_SYNC_PATH,
)


async def run_paycor_create_sync(
    client: httpx.AsyncClient,
) -> None:
    """Call the recent Paycor hires synchronization endpoint."""
    try:
        response = await client.post(PAYCOR_CREATE_SYNC_PATH)
        response.raise_for_status()
    except httpx.HTTPError:
        # A later scheduled run can retry the synchronization.
        return


async def run_paycor_update_sync(
    client: httpx.AsyncClient,
) -> None:
    """Call the Paycor employee update synchronization endpoint."""
    try:
        response = await client.post(PAYCOR_UPDATE_SYNC_PATH)
        response.raise_for_status()
    except httpx.HTTPError:
        # The next five-minute run retries the synchronization.
        return
