from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.features.auth.routers import router as auth_router
from app.features.caseware_cloud_intergration.routers import (
    create_caseware_router,
    entity_engagement_mapping_router,
    integration_log_router,
    update_caseware_router,
)
from app.features.exception_logs import install_exception_logging
from app.features.schedular_services import SchedulerService

from app.features.cch_axcess_integration.routers.create_cch_axcess_router import router as cch_axcess_router

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Database connections are created lazily by SQLAlchemy and disposed on exit.
    from app.db.session import engine

    scheduler_service = SchedulerService(get_settings())
    await scheduler_service.start()
    try:
        yield
    finally:
        await scheduler_service.shutdown()
        await engine.dispose()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    lifespan=lifespan,
)
install_exception_logging(app)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(create_caseware_router, prefix=settings.api_v1_prefix)
app.include_router(update_caseware_router, prefix=settings.api_v1_prefix)
app.include_router(entity_engagement_mapping_router, prefix=settings.api_v1_prefix)
app.include_router(integration_log_router, prefix=settings.api_v1_prefix)
app.include_router(cch_axcess_router, prefix=settings.api_v1_prefix)