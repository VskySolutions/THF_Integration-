"""Batch orchestration will be added here step by step."""

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class ConsolidatedSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run_bulk(
        self,
        request_id: uuid.UUID,
        trigger_type: str,
    ) -> dict[str, Any]:
        raise HTTPException(
            status_code=501,
            detail="The v1 consolidated batch flow is not implemented yet",
        )
