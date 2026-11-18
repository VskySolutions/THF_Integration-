import logging
import uuid

import httpx

from app.features.schedular_services.constants import (
    PAYCOR_TIMESHEET_SCHEDULED_SYNC_PATH,
)


LOGGER = logging.getLogger(__name__)


async def run_paycor_timesheet_sync(
    client: httpx.AsyncClient,
    schedule_id: uuid.UUID,
) -> None:
    """Call one scheduled Maconomy-to-Paycor timesheet sync."""

    try:
        response = await client.post(
            f"{PAYCOR_TIMESHEET_SCHEDULED_SYNC_PATH}/{schedule_id}"
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        LOGGER.exception(
            "Scheduled Paycor timesheet synchronization failed: %s",
            exc,
        )
