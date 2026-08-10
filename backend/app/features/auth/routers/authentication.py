from fastapi import APIRouter

from app.features.auth.dependencies import AuthenticatedApiKey
from app.features.auth.schemas import AuthenticationStatus

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/verify", response_model=AuthenticationStatus)
async def verify_api_key(_: AuthenticatedApiKey) -> AuthenticationStatus:
    return AuthenticationStatus(authenticated=True)
