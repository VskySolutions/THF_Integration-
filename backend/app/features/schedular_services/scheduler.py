import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import Settings
from app.features.schedular_services.constants import MACONOMY_CASEWARE_SYNC_JOB_ID
from app.features.schedular_services.services import run_maconomy_caseware_sync


class SchedulerService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._scheduler: AsyncIOScheduler | None = None

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
            run_maconomy_caseware_sync,
            trigger="interval",
            minutes=self._settings.scheduler_interval_minutes,
            args=[client],
            id=MACONOMY_CASEWARE_SYNC_JOB_ID,
            name="Maconomy to CaseWare Cloud sync",
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
