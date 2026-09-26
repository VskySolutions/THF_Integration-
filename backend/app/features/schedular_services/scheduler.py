import asyncio

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import Settings
from app.features.schedular_services.constants import (
    MACONOMY_CASEWARE_SYNC_JOB_ID,
    MACONOMY_CCH_SYNC_JOB_ID,
)
from app.features.schedular_services.services import (
    run_maconomy_caseware_sync,
    run_maconomy_cch_sync,
)


class SchedulerService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._scheduler: AsyncIOScheduler | None = None
        self._cch_completed = asyncio.Event()
        self._cch_succeeded = False
        self._integration_lock = asyncio.Lock()

    async def start(self) -> None:
        if not self._settings.scheduler_enabled:
            return

        client = httpx.AsyncClient(
            base_url=self._settings.scheduler_api_url,
            headers={
                "X-API-KEY": self._settings.scheduler_api_key.get_secret_value(),
            },
            timeout=httpx.Timeout(
                self._settings.scheduler_request_timeout_seconds
            ),
        )
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            self._run_cch_sync,
            trigger="interval",
            minutes=self._settings.scheduler_cch_interval_minutes,
            args=[client],
            id=MACONOMY_CCH_SYNC_JOB_ID,
            name="Maconomy to CCH/XCM task mapping",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        scheduler.add_job(
            self._run_caseware_sync,
            trigger="interval",
            minutes=self._settings.scheduler_caseware_interval_minutes,
            args=[client],
            id=MACONOMY_CASEWARE_SYNC_JOB_ID,
            name="Maconomy to CaseWare Cloud sync after CCH",
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

    async def _run_cch_sync(self, client: httpx.AsyncClient) -> None:
        self._cch_completed.clear()
        async with self._integration_lock:
            self._cch_succeeded = await run_maconomy_cch_sync(client)
            self._cch_completed.set()

    async def _run_caseware_sync(self, client: httpx.AsyncClient) -> None:
        try:
            await asyncio.wait_for(
                self._cch_completed.wait(),
                timeout=self._settings.scheduler_request_timeout_seconds + 60,
            )
        except asyncio.TimeoutError:
            return

        async with self._integration_lock:
            if not self._cch_completed.is_set():
                return
            self._cch_completed.clear()
            if not self._cch_succeeded:
                return
            await run_maconomy_caseware_sync(client)
