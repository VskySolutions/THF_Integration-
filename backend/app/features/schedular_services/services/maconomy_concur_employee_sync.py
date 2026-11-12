import httpx
import logging

from app.features.schedular_services.constants import (
    SAP_CONCUR_EMPLOYEE_SYNC_PATH,
)

logger = logging.getLogger(__name__)


async def run_maconomy_concur_employee_sync(
    client: httpx.AsyncClient,
) -> None:
    """Call the Maconomy to SAP Concur 5-minute employee synchronization endpoint."""
    try:
        response = await client.post(SAP_CONCUR_EMPLOYEE_SYNC_PATH)
        response.raise_for_status()
        logger.info(
            "Maconomy to SAP Concur employee sync cycle completed successfully: %s",
            response.json(),
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "Maconomy to SAP Concur employee sync cycle failed (will retry next interval): %s",
            exc,
        )
        return

