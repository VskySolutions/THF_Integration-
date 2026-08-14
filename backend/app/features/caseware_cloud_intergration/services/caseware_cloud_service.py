from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.features.caseware_cloud_intergration.mappers import (
    map_maconomy_customer_to_caseware_address,
    map_maconomy_job_to_caseware_entity,
)


class CasewareCloudServiceError(Exception):
    pass


class CasewareCloudService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    async def create_entity(self, maconomy_job_data: dict[str, Any]) -> dict[str, Any]:
        try:
            entity_data = map_maconomy_job_to_caseware_entity(maconomy_job_data)
        except ValueError as exc:
            raise CasewareCloudServiceError(str(exc)) from exc

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token(client)
                response = await client.post(
                    f"{self.settings.caseware_cloud_url}/api/v2/entities",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=entity_data,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CasewareCloudServiceError("Caseware Cloud request failed") from exc

        try:
            response_data = response.json()
            return {
                "CWGuid": response_data["CWGuid"],
                "Id": response_data["Id"],
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise CasewareCloudServiceError(
                "Invalid Caseware Cloud entity response"
            ) from exc

    async def create_entity_address(
        self,
        maconomy_customer_data: dict[str, Any],
        entity_cw_guid: str,
        entity_cw_owner_id: int,
    ) -> dict[str, int]:
        try:
            address_data = map_maconomy_customer_to_caseware_address(
                maconomy_customer_data,
                entity_cw_guid,
                entity_cw_owner_id,
            )
        except ValueError as exc:
            raise CasewareCloudServiceError(str(exc)) from exc

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token(client)
                response = await client.post(
                    f"{self.settings.caseware_cloud_url}/api/v2/entities/"
                    f"{entity_cw_guid}/addresses",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=address_data,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CasewareCloudServiceError(
                "Caseware Cloud address request failed"
            ) from exc

        try:
            address_id = response.json()["Id"]
        except (KeyError, TypeError, ValueError) as exc:
            raise CasewareCloudServiceError(
                "Invalid Caseware Cloud address response"
            ) from exc

        if not isinstance(address_id, int) or isinstance(address_id, bool):
            raise CasewareCloudServiceError("Invalid Caseware Cloud address response")
        return {"Id": address_id}

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{self.settings.caseware_cloud_url}/api/v2/auth/token",
            headers={"Content-Type": "application/json"},
            json={
                "ClientId": self.settings.caseware_cloud_client_id,
                "ClientSecret": (
                    self.settings.caseware_cloud_client_secret.get_secret_value()
                ),
                "Language": self.settings.caseware_cloud_language,
            },
        )
        response.raise_for_status()

        try:
            token = response.json()["Token"]
        except (KeyError, TypeError, ValueError) as exc:
            raise CasewareCloudServiceError(
                "Invalid Caseware Cloud authentication response"
            ) from exc

        if not isinstance(token, str) or not token:
            raise CasewareCloudServiceError(
                "Invalid Caseware Cloud authentication response"
            )
        return token
