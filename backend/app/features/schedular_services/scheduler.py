import logging

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import Settings
from app.features.schedular_services.constants import CASEWARE_SYNC_SEQUENCE_JOB_ID
from app.features.schedular_services.services import run_caseware_sync_sequence

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._scheduler: AsyncIOScheduler | None = None

    async def start(self) -> None:
        if not self._settings.scheduler_enabled:
            logger.info("Scheduled integration services are disabled")
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
            run_caseware_sync_sequence,
            trigger="interval",
            minutes=self._settings.scheduler_interval_minutes,
            args=[client],
            id=CASEWARE_SYNC_SEQUENCE_JOB_ID,
            name="CaseWare created-engagement then updated-engagement sync",
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
        logger.info(
            "Scheduled integration services started with interval_minutes=%s",
            self._settings.scheduler_interval_minutes,
        )

    async def shutdown(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduled integration services stopped")

        if self._client is not None:
            await self._client.aclose()

        self._scheduler = None
        self._client = None
