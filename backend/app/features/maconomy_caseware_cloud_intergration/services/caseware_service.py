import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import monotonic
from typing import Any

import httpx

from app.core.config import Settings


class CasewareServiceError(Exception):
    pass


class CasewareService:
    _max_rate_limit_retries = 3
    _cached_access_token: str | None = None
    _token_expires_at: float = 0.0
    _token_cache_key: tuple[str, str, str] | None = None
    _token_lock = asyncio.Lock()

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def _get_access_token(self) -> str:
        cache_key = (
            self.settings.caseware_cloud_url,
            self.settings.caseware_cloud_client_id,
            self.settings.caseware_cloud_language,
        )
        if (
            self.__class__._cached_access_token
            and self.__class__._token_cache_key == cache_key
            and monotonic() < self.__class__._token_expires_at
        ):
            return self.__class__._cached_access_token

        async with self.__class__._token_lock:
            if (
                self.__class__._cached_access_token
                and self.__class__._token_cache_key == cache_key
                and monotonic() < self.__class__._token_expires_at
            ):
                return self.__class__._cached_access_token

            try:
                response = await self.client.post(
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
            except httpx.HTTPStatusError as exc:
                raise CasewareServiceError(
                    f"CaseWare authentication failed (HTTP {exc.response.status_code})"
                ) from exc
            except httpx.HTTPError as exc:
                raise CasewareServiceError(
                    "CaseWare authentication request failed"
                ) from exc

            try:
                token = response.json()["Token"]
            except (KeyError, TypeError, ValueError) as exc:
                raise CasewareServiceError(
                    "Invalid CaseWare authentication response"
                ) from exc
            if not isinstance(token, str) or not token.strip():
                raise CasewareServiceError(
                    "Invalid CaseWare authentication response"
                )

            self.__class__._cached_access_token = token
            self.__class__._token_cache_key = cache_key
            self.__class__._token_expires_at = monotonic() + (29 * 60)
            return token

    @classmethod
    def _clear_cached_token(cls) -> None:
        cls._cached_access_token = None
        cls._token_expires_at = 0.0
        cls._token_cache_key = None

    async def find_entities_by_job_numbers(
        self, job_numbers: list[str]
    ) -> dict[str, dict[str, Any] | None]:
        unique_job_numbers = list(dict.fromkeys(job_numbers))
        if any(not job_number.strip() for job_number in unique_job_numbers):
            raise CasewareServiceError("CaseWare EntityNo cannot be empty")
        if not unique_job_numbers:
            return {}

        # Authenticate once and reuse this token for every EntityNo search.
        token = await self._get_access_token()
        url = f"{self.settings.caseware_cloud_url}/api/v2/entities"
        matches: dict[str, dict[str, Any] | None] = {}

        for job_number in unique_job_numbers:
            entity_number = f"VSKY-{job_number.strip()}"
            try:
                response, token = await self._search_entity(
                    url=url,
                    token=token,
                    entity_number=entity_number,
                )
            except httpx.HTTPStatusError as exc:
                retry_after = exc.response.headers.get("Retry-After")
                retry_detail = (
                    f"; retry after {retry_after} seconds" if retry_after else ""
                )
                raise CasewareServiceError(
                    "CaseWare entity search failed "
                    f"(HTTP {exc.response.status_code}{retry_detail})"
                ) from exc
            except httpx.HTTPError as exc:
                raise CasewareServiceError(
                    "CaseWare entity search request failed"
                ) from exc

            try:
                entities = response.json()
            except ValueError as exc:
                raise CasewareServiceError(
                    "Invalid CaseWare entity search response"
                ) from exc
            if not isinstance(entities, list) or any(
                not isinstance(entity, dict) for entity in entities
            ):
                raise CasewareServiceError(
                    "Invalid CaseWare entity search response"
                )

            exact_matches = [
                entity
                for entity in entities
                if entity.get("EntityNo") == entity_number
            ]
            if len(exact_matches) > 1:
                raise CasewareServiceError(
                    f"Multiple CaseWare entities found with EntityNo {entity_number}"
                )
            matches[job_number] = exact_matches[0] if exact_matches else None

        return matches

    async def _search_entity(
        self,
        *,
        url: str,
        token: str,
        entity_number: str,
    ) -> tuple[httpx.Response, str]:
        rate_limit_retries = 0
        token_was_refreshed = False
        escaped_entity_number = entity_number.replace("'", "''")

        while True:
            response = await self.client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "search": f"EntityNo='{escaped_entity_number}'",
                    "page": 1,
                    "pageSize": 50,
                },
            )

            if response.status_code == 401 and not token_was_refreshed:
                self._clear_cached_token()
                token = await self._get_access_token()
                token_was_refreshed = True
                continue

            if response.status_code != 429:
                response.raise_for_status()
                return response, token

            if rate_limit_retries >= self._max_rate_limit_retries:
                response.raise_for_status()

            delay_seconds = self._rate_limit_delay(
                response,
                retry_number=rate_limit_retries,
            )
            rate_limit_retries += 1
            await asyncio.sleep(delay_seconds)

    @staticmethod
    def _rate_limit_delay(
        response: httpx.Response,
        *,
        retry_number: int,
    ) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
                    return max(0.0, seconds)
                except (TypeError, ValueError, OverflowError):
                    pass

        return float(2 ** (retry_number + 1))

    async def update_entity(
        self,
        job: dict[str, Any],
        entity_cw_guid: str,
    ) -> dict[str, Any]:
        current_entity = await self._get_entity(entity_cw_guid)
        current_guid = current_entity.get("CWGuid")
        if not isinstance(current_guid, str) or current_guid.casefold() != entity_cw_guid.casefold():
            raise CasewareServiceError("CaseWare entity response does not match mapping")

        job_name = job.get("jobname")
        if not job_name:
            raise CasewareServiceError("Maconomy jobname is required for entity update")
        await self._request(
            "PATCH",
            f"/api/v2/entities/{entity_cw_guid}",
            json={
                "Name": str(job_name),
                "OperatingName": str(job_name),
                "OwnerType": "Client",
                "Type": "A",
            },
        )
        return current_entity

    async def create_entity(self, job: dict[str, Any]) -> dict[str, Any]:
        job_number = job.get("jobnumber")
        job_name = job.get("jobname")
        if not job_number or not job_name:
            raise CasewareServiceError(
                "Maconomy jobnumber and jobname are required for entity creation"
            )
        response = await self._request(
            "POST",
            "/api/v2/entities",
            json={
                "Id": 0,
                "EntityNo": f"VSKY-{job_number}",
                "Name": str(job_name),
                "OwnerType": "Client",
                "CountryCode": "US",
                "OperatingName": str(job_name),
                "OrganizationType": "Corporation",
                "Type": "A",
            },
        )
        try:
            entity = response.json()
        except (TypeError, ValueError) as exc:
            raise CasewareServiceError("Invalid CaseWare entity creation response") from exc
        if not isinstance(entity, dict):
            raise CasewareServiceError("Invalid CaseWare entity creation response")
        entity_guid = entity.get("CWGuid")
        owner_id = entity.get("Id")
        if not isinstance(entity_guid, str) or not entity_guid.strip():
            raise CasewareServiceError("Created CaseWare entity has an invalid CWGuid")
        if isinstance(owner_id, bool) or not isinstance(owner_id, int):
            raise CasewareServiceError("Created CaseWare entity has an invalid Id")
        return {"CWGuid": entity_guid, "Id": owner_id, **entity}

    async def get_entity_addresses(self, entity_cw_guid: str) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            f"/api/v2/entities/{entity_cw_guid}/addresses",
            params={"page": 1, "pageSize": 50},
        )
        try:
            addresses = response.json()
        except (TypeError, ValueError) as exc:
            raise CasewareServiceError("Invalid CaseWare address response") from exc
        if not isinstance(addresses, list) or any(
            not isinstance(address, dict) for address in addresses
        ):
            raise CasewareServiceError("Invalid CaseWare address response")
        return addresses

    async def update_entity_address(
        self,
        job: dict[str, Any],
        address_cw_guid: str,
    ) -> dict[str, Any]:
        if not isinstance(address_cw_guid, str) or not address_cw_guid.strip():
            raise CasewareServiceError("Invalid CaseWare address CWGuid")
        await self._request(
            "PATCH",
            f"/api/v2/entities/addresses/{address_cw_guid}",
            json=self._address_update_payload(job),
        )
        return {"CWGuid": address_cw_guid}

    async def create_entity_address(
        self,
        job: dict[str, Any],
        entity_cw_guid: str,
        entity_owner_id: int,
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            f"/api/v2/entities/{entity_cw_guid}/addresses",
            json={
                "Id": 0,
                **self._address_update_payload(job),
                "OwnerCWGuid": entity_cw_guid,
                "OwnerId": entity_owner_id,
            },
        )
        try:
            address_number = response.json()
        except (TypeError, ValueError) as exc:
            raise CasewareServiceError("Invalid CaseWare created address response") from exc
        if isinstance(address_number, bool) or not isinstance(address_number, int):
            raise CasewareServiceError("Invalid CaseWare created address response")

        addresses = await self.get_entity_addresses(entity_cw_guid)
        for address in addresses:
            if address.get("Id") == address_number:
                address_guid = address.get("CWGuid")
                if not isinstance(address_guid, str) or not address_guid.strip():
                    break
                return {"Id": address_number, "CWGuid": address_guid}
        raise CasewareServiceError("Created CaseWare address was not found")

    async def _get_entity(self, entity_cw_guid: str) -> dict[str, Any]:
        response = await self._request("GET", f"/api/v2/entities/{entity_cw_guid}")
        try:
            entity = response.json()
        except (TypeError, ValueError) as exc:
            raise CasewareServiceError("Invalid CaseWare entity response") from exc
        if not isinstance(entity, dict):
            raise CasewareServiceError("Invalid CaseWare entity response")
        return entity

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        token = await self._get_access_token()
        token_was_refreshed = False
        rate_limit_retries = 0
        while True:
            try:
                response = await self.client.request(
                    method,
                    f"{self.settings.caseware_cloud_url}{path}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=json,
                    params=params,
                )
            except httpx.HTTPError as exc:
                raise CasewareServiceError(f"CaseWare {method} request failed") from exc

            if response.status_code == 401 and not token_was_refreshed:
                self._clear_cached_token()
                token = await self._get_access_token()
                token_was_refreshed = True
                continue

            if response.status_code == 429:
                if rate_limit_retries >= self._max_rate_limit_retries:
                    raise CasewareServiceError(
                        f"CaseWare {method} request failed (HTTP 429)"
                    )
                await asyncio.sleep(
                    self._rate_limit_delay(
                        response,
                        retry_number=rate_limit_retries,
                    )
                )
                rate_limit_retries += 1
                continue
            break

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CasewareServiceError(
                f"CaseWare {method} request failed (HTTP {exc.response.status_code})"
            ) from exc
        except httpx.HTTPError as exc:
            raise CasewareServiceError(f"CaseWare {method} request failed") from exc
        return response

    @staticmethod
    def _address_update_payload(job: dict[str, Any]) -> dict[str, Any]:
        return {
            "Address1": job.get("name2", ""),
            "Address2": job.get("name3", ""),
            "Address3": job.get("name4", ""),
            "AddressCategory": "Business",
            "City": job.get("postaldistrict", ""),
            "Country": job.get("country", ""),
            "Name": job.get("name1", ""),
        }
