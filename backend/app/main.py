from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.features.auth.routers import router as auth_router
from app.features.caseware_cloud_intergration.routers import (
    entity_engagement_mapping_router,
    integration_log_router,
)
from app.features.exception_logs import install_exception_logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Database connections are created lazily by SQLAlchemy and disposed on exit.
    from app.db.session import engine

    yield
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
app.include_router(entity_engagement_mapping_router, prefix=settings.api_v1_prefix)
app.include_router(integration_log_router, prefix=settings.api_v1_prefix)
