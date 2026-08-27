"""CCCH Axcess engagement creation routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key

router = APIRouter(
    prefix="/cch-axcess",
    tags=["cch-axcess-integration"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]

@router.post(
    "/cch-axccess-test",
    response_model=dict[str, Any]
)
async def sap_concur():
    return {
        "message": "CCH Axcess Integration"
    }