import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.features.exception_logs.services import log_exception


def install_exception_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        supplied_id = request.headers.get("X-Request-ID")
        try:
            request.state.request_id = (
                uuid.UUID(supplied_id) if supplied_id else uuid.uuid4()
            )
        except ValueError:
            request.state.request_id = uuid.uuid4()

        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        return response

    @app.exception_handler(HTTPException)
    async def handle_http_exception(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        message = str(exc.detail)
        await log_exception(request, exc, status_code=exc.status_code, message=message)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": jsonable_encoder(exc.detail),
                "request_id": str(request.state.request_id),
            },
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        await log_exception(
            request,
            exc,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="Request validation failed",
            extra_context={"validation_errors": exc.errors()},
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": jsonable_encoder(exc.errors()),
                "request_id": str(request.state.request_id),
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        await log_exception(
            request,
            exc,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=str(exc),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal server error",
                "request_id": str(request.state.request_id),
            },
        )
