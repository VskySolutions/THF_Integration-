from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key


router = APIRouter(
    prefix="/sap-concur",
    tags=["sap-concur-integration"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]

@router.post(
    "/sap-concur-test", 
    response_model=dict[str, Any]
)
async def sap_concur():
    return {
        "message": "SAP Concur Integration"
    }