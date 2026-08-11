from typing import Any

import httpx

from app.core.config import Settings, get_settings


class CasewareCloudServiceError(Exception):
    pass


class CasewareCloudService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    async def create_entity(self, entity_data: dict[str, Any]) -> dict[str, Any]:
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
            token = response.json()["token"]
        except (KeyError, TypeError, ValueError) as exc:
            raise CasewareCloudServiceError(
                "Invalid Caseware Cloud authentication response"
            ) from exc

        if not isinstance(token, str) or not token:
            raise CasewareCloudServiceError(
                "Invalid Caseware Cloud authentication response"
            )
        return token
