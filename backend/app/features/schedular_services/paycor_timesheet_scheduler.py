import asyncio

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import Settings
from app.features.schedular_services.constants import (
    PAYCOR_EASTERN_TIMEZONE,
    PAYCOR_TIMESHEET_SYNC_JOB_ID,
)
from app.features.schedular_services.services import (
    run_paycor_timesheet_sync,
)


class PaycorTimesheetSchedulerService:
    """Run the weekly Maconomy-to-Paycor timesheet sync."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._scheduler: AsyncIOScheduler | None = None
        self._timesheet_lock = asyncio.Lock()

    async def start(self) -> None:
        if not self._settings.scheduler_enabled:
            return

        client = httpx.AsyncClient(
            base_url=self._settings.scheduler_api_url,
            headers={
                "X-API-KEY": (
                    self._settings.scheduler_api_key.get_secret_value()
                ),
            },
            timeout=httpx.Timeout(
                self._settings.scheduler_request_timeout_seconds
            ),
        )
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            self._run_timesheet_sync,
            trigger="cron",
            day_of_week=(
                self._settings
                .scheduler_paycor_timesheet_day_of_week
            ),
            hour=(
                self._settings
                .scheduler_paycor_timesheet_hour_et
            ),
            minute=(
                self._settings
                .scheduler_paycor_timesheet_minute_et
            ),
            second=0,
            timezone=PAYCOR_EASTERN_TIMEZONE,
            args=[client],
            id=PAYCOR_TIMESHEET_SYNC_JOB_ID,
            name="Maconomy to Paycor weekly timesheet sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        try:
            scheduler.start()
        except Exception:
            await client.aclose()
            raise

        self._client = client
        self._scheduler = scheduler

    async def shutdown(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)

        if self._client is not None:
            await self._client.aclose()

        self._scheduler = None
        self._client = None

    async def _run_timesheet_sync(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        async with self._timesheet_lock:
            await run_paycor_timesheet_sync(client)
