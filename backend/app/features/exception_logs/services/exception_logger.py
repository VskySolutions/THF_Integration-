import logging
import traceback
import uuid
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder

from app.db.session import AsyncSessionFactory
from app.features.exception_logs.models import ExceptionLog

logger = logging.getLogger(__name__)


async def log_exception(
    request: Request,
    exc: Exception,
    *,
    status_code: int,
    message: str,
    extra_context: dict[str, Any] | None = None,
) -> None:
    """Persist an exception without allowing logging failures to mask it."""
    route = request.scope.get("route")
    endpoint = getattr(route, "path", request.url.path)
    request_id = getattr(request.state, "request_id", None)
    context: dict[str, Any] = {
        "status_code": status_code,
        "client_host": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "path_params": dict(request.path_params),
    }
    if extra_context:
        context.update(extra_context)

    entry = ExceptionLog(
        id=uuid.uuid4(),
        request_id=request_id,
        endpoint=endpoint,
        http_method=request.method[:10],
        exception_type=type(exc).__name__[:255],
        message=message,
        stack_trace="".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ),
        context=jsonable_encoder(context),
    )

    try:
        async with AsyncSessionFactory() as session:
            session.add(entry)
            await session.commit()
    except Exception:
        logger.exception("Unable to persist exception log for request %s", request_id)
