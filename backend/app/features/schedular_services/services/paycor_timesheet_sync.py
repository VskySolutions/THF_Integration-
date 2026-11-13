import logging

import httpx

from app.features.schedular_services.constants import (
    PAYCOR_TIMESHEET_SYNC_PATH,
)


LOGGER = logging.getLogger(__name__)


async def run_paycor_timesheet_sync(
    client: httpx.AsyncClient,
) -> None:
    """Call the weekly Maconomy-to-Paycor timesheet sync endpoint."""

    try:
        response = await client.post(
            PAYCOR_TIMESHEET_SYNC_PATH
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        LOGGER.exception(
            "Scheduled Paycor timesheet synchronization failed: %s",
            exc,
        )
