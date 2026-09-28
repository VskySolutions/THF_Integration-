from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authentication.dependencies import CurrentUser
from app.authentication.models import User
from app.authentication.security import (
    DUMMY_PASSWORD_HASH,
    ensure_csrf_token,
    valid_csrf_token,
    verify_password,
)
from app.db.session import get_db
from app.web.templating import templates

router = APIRouter(tags=["dashboard authentication"])


@router.get("/login", response_class=HTMLResponse, name="login")
async def login_page(request: Request, current_user: CurrentUser) -> HTMLResponse:
    if current_user is not None:
        return RedirectResponse(
            request.url_for("dashboard"), status_code=status.HTTP_303_SEE_OTHER
        )

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"csrf_token": ensure_csrf_token(request)},
    )


@router.post("/login", response_class=HTMLResponse)
async def log_in(
    request: Request,
    username_or_email: Annotated[str, Form(min_length=1, max_length=320)],
    password: Annotated[str, Form(min_length=1, max_length=1024)],
    csrf_token: Annotated[str, Form(min_length=1)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    identifier = username_or_email.strip()
    if not valid_csrf_token(request, csrf_token):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "csrf_token": ensure_csrf_token(request),
                "error": "Your login form expired. Please try again.",
                "username_or_email": identifier,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    result = await session.execute(
        select(User).where(
            or_(
                func.lower(User.username) == identifier.lower(),
                func.lower(User.email_id) == identifier.lower(),
            ),
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()
    stored_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH

    if user is None or not verify_password(password, stored_hash):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "csrf_token": ensure_csrf_token(request),
                "error": "Invalid username/email or password.",
                "username_or_email": identifier,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    request.session.clear()
    request.session["user_id"] = str(user.id)
    ensure_csrf_token(request)
    return RedirectResponse(
        request.url_for("dashboard"), status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/logout", name="logout")
async def log_out(
    request: Request,
    csrf_token: Annotated[str, Form(min_length=1)],
) -> RedirectResponse:
    if not valid_csrf_token(request, csrf_token):
        return RedirectResponse(
            request.url_for("dashboard"), status_code=status.HTTP_303_SEE_OTHER
        )

    request.session.clear()
    return RedirectResponse(
        request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER
    )
