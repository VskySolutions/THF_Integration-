"""Run the customer discovery step of the v1 bulk integration."""

import logging
import uuid
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.hubspot_contact_consolidated_integration_v1.exceptions import (
    MaconomyError,
)
from app.features.hubspot_contact_consolidated_integration_v1.services.maconomy_service import (
    MaconomyService,
)

logger = logging.getLogger(__name__)


class ConsolidatedSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run_bulk(
        self,
        request_id: uuid.UUID,
        trigger_type: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            maconomy = MaconomyService(client)
            try:
                await maconomy.authenticate()
                customers = await maconomy.discover_customers()
            except MaconomyError as exc:
                logger.exception(
                    "v1 Maconomy bulk read failed: request_id=%s stage=%s "
                    "reason=%s upstream_status=%s",
                    request_id,
                    exc.stage,
                    exc.reason,
                    exc.upstream_status,
                )
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        return maconomy.classify_customers(customers)
