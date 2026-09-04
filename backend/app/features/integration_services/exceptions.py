from fastapi import HTTPException, status

from app.features.integration_services.constants import IntegrationServiceIdentifier


class IntegrationServiceUnavailableError(HTTPException):
    def __init__(
        self,
        *,
        service_identifier: IntegrationServiceIdentifier,
        code: str,
        message: str,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": code,
                "message": message,
                "service_identifier": service_identifier.value,
            },
        )


class IntegrationServiceInactiveError(IntegrationServiceUnavailableError):
    def __init__(self, service_identifier: IntegrationServiceIdentifier) -> None:
        super().__init__(
            service_identifier=service_identifier,
            code="INTEGRATION_SERVICE_INACTIVE",
            message="Integration service is inactive",
        )


class IntegrationServiceNotConfiguredError(IntegrationServiceUnavailableError):
    def __init__(self, service_identifier: IntegrationServiceIdentifier) -> None:
        super().__init__(
            service_identifier=service_identifier,
            code="INTEGRATION_SERVICE_NOT_CONFIGURED",
            message="Integration service is not configured",
        )
