"""X-API-KEY authentication feature."""

from app.features.auth.dependencies import require_api_key

__all__ = ["require_api_key"]
