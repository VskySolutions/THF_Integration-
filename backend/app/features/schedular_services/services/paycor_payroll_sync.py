import httpx

from app.features.schedular_services.constants import (
    PAYCOR_PAYROLL_SYNC_PATH,
)


async def run_paycor_payroll_sync(
    client: httpx.AsyncClient,
) -> None:
    """Call the Paycor payroll-to-Maconomy sync endpoint."""
    try:
        response = await client.post(PAYCOR_PAYROLL_SYNC_PATH)
        response.raise_for_status()
    except httpx.HTTPError:
        # Errors are logged inside the endpoint; retry on next scheduled run.
        return

