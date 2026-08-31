import logging
from time import monotonic

import httpx

from app.features.schedular_services.constants import (
    SYNC_CREATED_PATH,
    SYNC_UPDATED_PATH,
)

logger = logging.getLogger(__name__)


async def run_caseware_sync_sequence(client: httpx.AsyncClient) -> None:
    """Run both CaseWare sync APIs in order, regardless of individual failures."""
    logger.info("Starting scheduled CaseWare create-then-update sync sequence")

    created_succeeded = await _run_step_safely(
        client,
        path=SYNC_CREATED_PATH,
        step_name="created-engagement sync",
    )
    updated_succeeded = await _run_step_safely(
        client,
        path=SYNC_UPDATED_PATH,
        step_name="updated-engagement sync",
    )

    logger.info(
        "Scheduled CaseWare sync sequence completed; created_success=%s; "
        "updated_success=%s",
        created_succeeded,
        updated_succeeded,
    )


async def _run_step_safely(
    client: httpx.AsyncClient,
    *,
    path: str,
    step_name: str,
) -> bool:
    started_at = monotonic()
    try:
        response = await client.post(path)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Scheduled %s failed with HTTP status %s after %.2f seconds",
            step_name,
            exc.response.status_code,
            monotonic() - started_at,
        )
        return False
    except httpx.RequestError as exc:
        logger.error(
            "Scheduled %s request failed after %.2f seconds: %s",
            step_name,
            monotonic() - started_at,
            exc,
        )
        return False
    except Exception:
        logger.exception(
            "Scheduled %s failed unexpectedly after %.2f seconds",
            step_name,
            monotonic() - started_at,
        )
        return False

    logger.info(
        "Scheduled %s completed with HTTP status %s in %.2f seconds",
        step_name,
        response.status_code,
        monotonic() - started_at,
    )
    return True
