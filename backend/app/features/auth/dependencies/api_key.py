import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings

api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)


async def require_api_key(
    provided_key: Annotated[str | None, Security(api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    if provided_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-KEY header is required",
        )

    if not any(
        secrets.compare_digest(provided_key, accepted_key)
        for accepted_key in settings.accepted_api_keys
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return provided_key


AuthenticatedApiKey = Annotated[str, Depends(require_api_key)]
