import asyncio

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import Settings
from app.features.schedular_services.constants import (
    PAYCOR_CREATE_SYNC_JOB_ID,
    PAYCOR_EASTERN_TIMEZONE,
    PAYCOR_UPDATE_SYNC_JOB_ID,
)
from app.features.schedular_services.services import (
    run_paycor_create_sync,
    run_paycor_update_sync,
)


class PaycorSchedulerService:
    """Run Paycor jobs independently from the existing integrations."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._scheduler: AsyncIOScheduler | None = None
        self._paycor_lock = asyncio.Lock()

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

        create_start_hour = (
            self._settings.scheduler_paycor_create_start_hour_et
        )
        create_hours = (
            f"{create_start_hour},"
            f"{(create_start_hour + 12) % 24}"
        )

        # The create job starts one second before an update boundary. The
        # shared Paycor lock then makes a coincident update wait for creation.
        scheduler.add_job(
            self._run_create_sync,
            trigger="cron",
            hour=create_hours,
            minute=0,
            second=0,
            timezone=PAYCOR_EASTERN_TIMEZONE,
            args=[client],
            id=PAYCOR_CREATE_SYNC_JOB_ID,
            name="Paycor recent hires create sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        scheduler.add_job(
            self._run_update_sync,
            trigger="cron",
            minute=(
                "*/"
                f"{self._settings.scheduler_paycor_update_interval_minutes}"
            ),
            second=1,
            timezone="UTC",
            args=[client],
            id=PAYCOR_UPDATE_SYNC_JOB_ID,
            name="Paycor employee update sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
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

    async def _run_create_sync(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        async with self._paycor_lock:
            await run_paycor_create_sync(client)

    async def _run_update_sync(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        async with self._paycor_lock:
            await run_paycor_update_sync(client)
