import asyncio
import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import Settings
from app.db.session import AsyncSessionFactory
from app.features.paycor_integration.services.timesheet_schedule_service import (
    list_pending_schedules,
)
from app.features.schedular_services.constants import (
    PAYCOR_EASTERN_TIMEZONE,
    PAYCOR_TIMESHEET_SYNC_JOB_ID_PREFIX,
)
from app.features.schedular_services.services import (
    run_paycor_timesheet_sync,
)


class PaycorTimesheetSchedulerService:
    """Run database-scheduled Maconomy-to-Paycor timesheet syncs."""

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
        eastern_timezone = ZoneInfo(PAYCOR_EASTERN_TIMEZONE)
        current_eastern_date = datetime.now(
            eastern_timezone
        ).date()

        async with AsyncSessionFactory() as session:
            schedules = await list_pending_schedules(
                session,
                from_date=current_eastern_date,
            )

        for schedule in schedules:
            run_datetime = datetime.combine(
                schedule.import_from_maconomy_date,
                time(
                    hour=(
                        self._settings
                        .scheduler_paycor_timesheet_hour_et
                    ),
                    minute=(
                        self._settings
                        .scheduler_paycor_timesheet_minute_et
                    ),
                ),
                tzinfo=eastern_timezone,
            )
            scheduler.add_job(
                self._run_timesheet_sync,
                trigger="date",
                run_date=run_datetime,
                args=[client, schedule.id],
                id=(
                    f"{PAYCOR_TIMESHEET_SYNC_JOB_ID_PREFIX}_"
                    f"{schedule.id}"
                ),
                name=(
                    "Maconomy to Paycor scheduled timesheet sync "
                    f"{schedule.id}"
                ),
                replace_existing=True,
                max_instances=1,
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
        schedule_id: uuid.UUID,
    ) -> None:
        async with self._timesheet_lock:
            await run_paycor_timesheet_sync(
                client,
                schedule_id,
            )
