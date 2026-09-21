import httpx

from app.features.schedular_services.constants import MACONOMY_CASEWARE_SYNC_PATH


async def run_maconomy_caseware_sync(client: httpx.AsyncClient) -> None:
    """Call the Maconomy-first CaseWare sync endpoint."""
    try:
        response = await client.post(MACONOMY_CASEWARE_SYNC_PATH)
        response.raise_for_status()
    except httpx.HTTPError:
        # The scheduler must finish this run cleanly; the next interval retries.
        return
