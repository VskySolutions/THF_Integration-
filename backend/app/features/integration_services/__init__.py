"""Shared integration-service availability controls."""

from app.features.integration_services.constants import IntegrationServiceIdentifier
from app.features.integration_services.dependencies import (
    require_active_integration_service,
)

__all__ = [
    "IntegrationServiceIdentifier",
    "require_active_integration_service",
]
