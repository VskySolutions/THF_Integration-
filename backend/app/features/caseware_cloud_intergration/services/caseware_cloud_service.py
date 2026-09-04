from typing import Any
import time
import asyncio

import httpx

from app.core.config import Settings, get_settings
from app.features.caseware_cloud_intergration.mappers import (
    map_maconomy_customer_to_caseware_address,
    map_maconomy_job_to_caseware_address_update,
    map_maconomy_job_to_caseware_entity,
    map_maconomy_job_to_caseware_entity_update,
)


class CasewareCloudServiceError(Exception):
    pass


class CasewareCloudEntityCreationError(CasewareCloudServiceError):
    def __init__(self, message: str, *, reconciliation_allowed: bool) -> None:
        super().__init__(message)
        self.reconciliation_allowed = reconciliation_allowed


class CasewareCloudService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

        self._access_token: str | None = None
        self._token_expires_at: float = 0

        # Prevent multiple async requests from requesting a token simultaneously
        self._token_lock = asyncio.Lock()

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
        except httpx.HTTPStatusError as exc:
            reconciliation_allowed = exc.response.status_code not in (401, 403)
            raise CasewareCloudEntityCreationError(
                "Caseware Cloud entity request failed",
                reconciliation_allowed=reconciliation_allowed,
            ) from exc
        except httpx.RequestError as exc:
            raise CasewareCloudEntityCreationError(
                "Caseware Cloud entity request result is uncertain",
                reconciliation_allowed=True,
            ) from exc

        try:
            response_data = response.json()
            return {
                "CWGuid": response_data["CWGuid"],
                "Id": response_data["Id"],
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise CasewareCloudEntityCreationError(
                "Invalid Caseware Cloud entity response",
                reconciliation_allowed=True,
            ) from exc

    async def get_entity_by_entity_number(
        self,
        entity_number: str,
    ) -> dict[str, Any] | None:
        if not entity_number.strip():
            raise CasewareCloudServiceError("Invalid CaseWare Cloud entity number")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token(client)
                response = await client.get(
                    f"{self.settings.caseware_cloud_url}/api/v2/entities",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    params={
                        "search": f"EntityNo='{entity_number}'",
                        "page": 1,
                        "pageSize": 50,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CasewareCloudServiceError(
                "Unable to reconcile entity in CaseWare Cloud"
            ) from exc

        try:
            entities = response.json()
        except (TypeError, ValueError) as exc:
            raise CasewareCloudServiceError(
                "Invalid CaseWare Cloud entity search response"
            ) from exc
        if not isinstance(entities, list) or any(
            not isinstance(entity, dict) for entity in entities
        ):
            raise CasewareCloudServiceError(
                "Invalid CaseWare Cloud entity search response"
            )

        matching_entities = [
            entity
            for entity in entities
            if entity.get("EntityNo") == entity_number
        ]
        if not matching_entities:
            return None
        if len(matching_entities) > 1:
            raise CasewareCloudServiceError(
                "CaseWare Cloud entity reconciliation is ambiguous and requires "
                "manual resolution"
            )

        entity = matching_entities[0]
        entity_id = entity.get("Id")
        entity_cw_guid = entity.get("CWGuid")
        if (
            not isinstance(entity_id, int)
            or isinstance(entity_id, bool)
            or not isinstance(entity_cw_guid, str)
            or not entity_cw_guid.strip()
        ):
            raise CasewareCloudServiceError(
                "Invalid CaseWare Cloud entity search response"
            )
        return entity

    async def update_entity(
        self,
        maconomy_job_data: dict[str, Any],
        entity_cw_guid: str,
    ) -> dict[str, str]:
        # Validate the CaseWare Cloud entity GUID
        if not entity_cw_guid.strip():
            raise CasewareCloudServiceError("Invalid CaseWare Cloud entity GUID")

        entity_url = (
            f"{self.settings.caseware_cloud_url}/api/v2/entities/{entity_cw_guid}"
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                token = await self._get_token(client)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                response = await client.get(entity_url, headers=headers)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise CasewareCloudServiceError(
                    "Unable to retrieve entity from CaseWare Cloud"
                ) from exc

            current_entity = self._parse_entity_response(response)
            current_guid = str(current_entity["CWGuid"])

            # Validate that the retrieved entity's GUID matches the provided GUID
            if self._normalize_guid(current_guid) != self._normalize_guid(
                entity_cw_guid
            ):
                raise CasewareCloudServiceError(
                    "Invalid CaseWare Cloud entity response"
                )

            # Map the Maconomy job data to the CaseWare Cloud entity update format
            try:
                update_data = map_maconomy_job_to_caseware_entity_update(
                    maconomy_job_data,
                    current_entity,
                )
            except ValueError as exc:
                raise CasewareCloudServiceError(str(exc)) from exc

            try:
                response = await client.patch(
                    entity_url,
                    headers=headers,
                    json=update_data,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise CasewareCloudServiceError(
                    "Unable to update entity in CaseWare Cloud"
                ) from exc

        return {"CWGuid": current_guid}

    async def update_entity_address(
        self,
        maconomy_job_data: dict[str, Any],
        address_cw_guid: str,
    ) -> dict[str, str]:
        if not isinstance(address_cw_guid, str) or not address_cw_guid.strip():
            raise CasewareCloudServiceError(
                "Invalid CaseWare Cloud address CWGuid"
            )

        address_data = map_maconomy_job_to_caseware_address_update(
            maconomy_job_data
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token(client)
                response = await client.patch(
                    f"{self.settings.caseware_cloud_url}/api/v2/entities/"
                    f"addresses/{address_cw_guid}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=address_data,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CasewareCloudServiceError(
                "Unable to update address in CaseWare Cloud"
            ) from exc

        return {"CWGuid": address_cw_guid}

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

                try:
                    address_id = response.json()
                except (TypeError, ValueError) as exc:
                    raise CasewareCloudServiceError(
                        "Invalid Caseware Cloud address response"
                    ) from exc

                if not isinstance(address_id, int) or isinstance(address_id, bool):
                    raise CasewareCloudServiceError(
                        "Invalid Caseware Cloud address response"
                    )
        except httpx.HTTPError as exc:
            raise CasewareCloudServiceError(
                "Caseware Cloud address request failed"
            ) from exc

        return {"Id": address_id}

    async def get_entity_detail(self, entity_cw_guid: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token(client)
                response = await client.get(
                    f"{self.settings.caseware_cloud_url}/api/v2/entities/"
                    f"{entity_cw_guid}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CasewareCloudServiceError(
                "Unable to retrieve entity from CaseWare Cloud"
            ) from exc

        entity_data = self._parse_entity_response(response)
        returned_cw_guid = str(entity_data["CWGuid"])
        if self._normalize_guid(returned_cw_guid) != self._normalize_guid(
            entity_cw_guid
        ):
            raise CasewareCloudServiceError(
                "Invalid CaseWare Cloud entity response"
            )
        entity_id = entity_data.get("Id")
        if not isinstance(entity_id, int) or isinstance(entity_id, bool):
            raise CasewareCloudServiceError(
                "Invalid CaseWare Cloud entity response"
            )
        return entity_data

    async def get_entity_addresses(
        self,
        entity_cw_guid: str,
    ) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token(client)
                response = await client.get(
                    f"{self.settings.caseware_cloud_url}/api/v2/entities/"
                    f"{entity_cw_guid}/addresses",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    params={"page": 1, "pageSize": 50},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CasewareCloudServiceError(
                "Unable to retrieve addresses from CaseWare Cloud"
            ) from exc

        try:
            addresses = response.json()
        except (TypeError, ValueError) as exc:
            raise CasewareCloudServiceError(
                "Invalid Caseware Cloud addresses response"
            ) from exc
        if not isinstance(addresses, list) or any(
            not isinstance(address, dict) for address in addresses
        ):
            raise CasewareCloudServiceError(
                "Invalid Caseware Cloud addresses response"
            )
        return addresses

    async def get_entity_address_by_id(
        self,
        entity_cw_guid: str,
        address_id: int,
    ) -> dict[str, int | str]:
        addresses = await self.get_entity_addresses(entity_cw_guid)
        return self._find_created_address(addresses, address_id)

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        # Return cached token if still valid
        if (
            self._access_token
            and time.time() < self._token_expires_at
        ):
            return self._access_token

        async with self._token_lock:
            if (
                self._access_token
                and time.time() < self._token_expires_at
            ):
                return self._access_token

            response = await client.post(
                f"{self.settings.caseware_cloud_url}/api/v2/auth/token",
                headers={
                    "Content-Type": "application/json",
                },
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
                data = response.json()
                token = data["Token"]
            except (KeyError, TypeError, ValueError) as exc:
                raise CasewareCloudServiceError(
                    "Invalid Caseware Cloud authentication response"
                ) from exc

            if not isinstance(token, str) or not token:
                raise CasewareCloudServiceError(
                    "Invalid Caseware Cloud authentication response"
                )

            self._access_token = token

            # IMPORTANT:
            # Replace this value with the actual CaseWare token lifetime
            # if the authentication response provides one.
            self._token_expires_at = time.time() + (28 * 60)

            return self._access_token

    @staticmethod
    def _parse_entity_response(response: httpx.Response) -> dict[str, Any]:
        try:
            entity_data = response.json()
        except (TypeError, ValueError) as exc:
            raise CasewareCloudServiceError(
                "Invalid CaseWare Cloud entity response"
            ) from exc

        required_fields = ("CWGuid", "EntityNo", "Name", "OwnerType", "Type")
        if not isinstance(entity_data, dict) or any(
            not entity_data.get(field) for field in required_fields
        ):
            raise CasewareCloudServiceError(
                "Invalid CaseWare Cloud entity response"
            )
        return entity_data

    @staticmethod
    def _normalize_guid(value: str) -> str:
        return value.strip().strip("{}").casefold()

    @staticmethod
    def _find_created_address(
        addresses: list[dict[str, Any]],
        address_id: int,
    ) -> dict[str, int | str]:
        matching_address = next(
            (
                address
                for address in addresses
                if isinstance(address, dict) and address.get("Id") == address_id
            ),
            None,
        )
        if matching_address is None:
            raise CasewareCloudServiceError(
                "Created Caseware Cloud address not found on entity"
            )

        address_cw_guid = matching_address.get("CWGuid")
        if not isinstance(address_cw_guid, str) or not address_cw_guid.strip():
            raise CasewareCloudServiceError(
                "Invalid Caseware Cloud address CWGuid"
            )
        matched_address_id = matching_address.get("Id")
        if not isinstance(matched_address_id, int) or isinstance(
            matched_address_id, bool
        ):
            raise CasewareCloudServiceError(
                "Invalid Caseware Cloud address ID"
            )
        return {
            "Id": matched_address_id,
            "CWGuid": address_cw_guid,
        }
