from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.features.caseware_cloud_intergration.services.caseware_cloud_service import CasewareCloudEntityCreationError
from app.features.cch_axcess_integration.mappers.client_mapper import map_maconomy_job_to_cch_client

class CCHAxcessServiceError(Exception):
    pass


class CCHAxcessClientCreationError(CCHAxcessServiceError):
    def __init__(self, message: str, *, reconciliation_allowed: bool) -> None:
        super().__init__(message)
        self.reconciliation_allowed = reconciliation_allowed


class CCHAxcessService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    # Get Access Token from CCH Axcess
    async def _get_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{self.settings.cch_axcess_url}/api/v2/auth/token",
            headers={"Content-Type": "application/json"},
            json={
                "ClientId": self.settings.cch_axcess_client_id,
                "ClientSecret": (
                    self.settings.cch_axcess_client_secret.get_secret_value()
                ),
                # "Language": self.settings.cch_axcess_language,
            },
        )
        response.raise_for_status()

        try:
            token = response.json()["Token"]
        except (KeyError, TypeError, ValueError) as exc:
            raise CCHAxcessServiceError(
                "Invalid CCH Axcess authentication response"
            ) from exc

        if not isinstance(token, str) or not token:
            raise CCHAxcessServiceError(
                "Invalid CCH Axcess authentication response"
            )
        return token


    # Create Client in CCH Axcess
    async def create_client(self, maconomy_job_data: dict[str, Any]) -> dict[str, Any]:
        try:
            entity_data = map_maconomy_job_to_cch_client(maconomy_job_data)
        except ValueError as exc:
            raise CCHAxcessServiceError(str(exc)) from exc

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token(client)
                response = await client.post(
                    f"{self.settings.cch_axcess_url}/api/v2.1/client",

                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=entity_data,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            reconciliation_allowed = exc.response.status_code not in (401, 403)
            raise CCHAxcessClientCreationError(
                "CCH Axcess client request failed",
                reconciliation_allowed=reconciliation_allowed,
            ) from exc
        except httpx.RequestError as exc:
            raise CCHAxcessClientCreationError(
                "CCH Axcess client request result is uncertain",
                reconciliation_allowed=True,
            ) from exc

        try:
            response_data = response.json()
            # Confirm required response fields are present and valid
            return {
                "client_id": response_data["clientId"],
                # "Id": response_data["Id"],
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise CCHAxcessClientCreationError(
                "Invalid CCH Axcess client response",
                reconciliation_allowed=True,
            ) from exc

