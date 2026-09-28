import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.authentication.models import User
from app.db.session import get_db


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    raw_user_id = request.session.get("user_id")
    if not isinstance(raw_user_id, str):
        return None

    try:
        user_id = uuid.UUID(raw_user_id)
    except ValueError:
        request.session.clear()
        return None

    result = await session.execute(
        select(User).where(
            User.id == user_id,
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        request.session.clear()
    return user


async def require_authenticated_user(
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return current_user


CurrentUser = Annotated[User | None, Depends(get_current_user)]
AuthenticatedUser = Annotated[User, Depends(require_authenticated_user)]
