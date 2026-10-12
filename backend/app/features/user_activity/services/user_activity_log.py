from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.user_activity.models import UserActivityLog


async def log_activity(
    session: AsyncSession,
    *,
    action: str,
    user: str,
    service: str | None = None,
    data: dict[str, Any] | None = None,
    status: str | None = None,
) -> UserActivityLog:
    log = UserActivityLog(
        action=action,
        service=service,
        data=data,
        user=user,
        status=status,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    return log
