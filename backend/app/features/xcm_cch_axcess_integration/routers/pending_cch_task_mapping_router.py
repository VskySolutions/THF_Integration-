from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.features.auth.dependencies import require_api_key
from app.features.xcm_cch_axcess_integration.services import (
    MaconomyService,
    MaconomyServiceError,
)

router = APIRouter(
    prefix="/xcm-cch-axcess",
    tags=["xcm-cch-axcess-integration"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "/maconomy-tax-engagements/pending-cch-task-mapping",
    response_model=list[dict[str, Any]],
)
async def process_pending_cch_task_mappings() -> list[dict[str, Any]]:
    """Find unsynced open TAX jobs created during the last two calendar days."""
    try:
        return await MaconomyService().get_syncable_tax_jobs()
    except MaconomyServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve pending tax engagements from Maconomy",
        ) from exc
