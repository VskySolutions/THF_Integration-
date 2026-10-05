"""Look up Maconomy job numbers as CCH client account numbers."""

from typing import Any

import httpx

from app.core.config import Settings, get_settings

CLIENT_SEARCH_PATH = "/xcmrestservices/vnext/api/v2/Client/search/advanced"
AUTH_PATH = "/xcmrestservices/vnext/api/v2/Authenticate/user"


class CCHClientServiceError(Exception):
    """Raised when CCH client existence cannot be determined."""


class CCHClientService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self._token: str | None = None

    async def authenticate(self) -> None:
        """Authenticate once for the client search in this integration run."""
        if self._token is not None:
            return
        try:
            response = await self.client.post(
                self._url(AUTH_PATH),
                headers={
                    "APIKey": self.settings.cch_axcess_api_key.get_secret_value(),
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={
                    "userName": self.settings.cch_axcess_user_name,
                    "password": self.settings.cch_axcess_password.get_secret_value(),
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CCHClientServiceError("CCH authentication request failed") from exc

        try:
            token = response.json()["token"]
        except (KeyError, TypeError, ValueError) as exc:
            raise CCHClientServiceError("Invalid CCH authentication response") from exc
        if not isinstance(token, str) or not token.strip():
            raise CCHClientServiceError("Invalid CCH authentication response")
        self._token = token.strip()

    async def flag_existing_clients(
        self,
        jobs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Add is_exist_in_chh using an exact AccountNumber match."""
        if not jobs:
            return []

        job_numbers: list[str] = []
        for job in jobs:
            value = job.get("jobnumber")
            if value is None or not str(value).strip():
                raise CCHClientServiceError("Maconomy jobnumber is required")
            job_numbers.append(str(value).strip())

        unique_numbers = list(dict.fromkeys(job_numbers))
        await self.authenticate()
        matching_numbers = await self._search_clients(
            unique_numbers,
            page_count=len(job_numbers),
        )

        return [
            {**job, "is_exist_in_chh": job_number in matching_numbers}
            for job, job_number in zip(jobs, job_numbers, strict=True)
        ]

    async def _search_clients(
        self,
        job_numbers: list[str],
        *,
        page_count: int,
    ) -> set[str]:
        filters = [
            {
                "condition": "" if index == 0 else "or",
                "key": "AccountNumber",
                "value": job_number,
            }
            for index, job_number in enumerate(job_numbers)
        ]
        try:
            print(filters)
            response = await self.client.post(
                self._url(CLIENT_SEARCH_PATH),
                headers=self._authorized_headers(),
                json={
                    "pageIndex": 1,
                    "pageCount": page_count+50,
                    "filters": filters,
                },
            )
            print(self._url(CLIENT_SEARCH_PATH))
            print(response.json())

            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CCHClientServiceError(
                f"CCH client search failed with HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise CCHClientServiceError("CCH client search request failed") from exc

        try:
            data = response.json()
            total_count = data["totalCount"]
            results = data["results"]
        except (KeyError, TypeError, ValueError) as exc:
            raise CCHClientServiceError("Invalid CCH client search response") from exc
        if (
            isinstance(total_count, bool)
            or not isinstance(total_count, int)
            or total_count < 0
            or not isinstance(results, list)
            or not all(isinstance(result, dict) for result in results)
        ):
            raise CCHClientServiceError("Invalid CCH client search response")

        requested_numbers = set(job_numbers)
        matches: set[str] = set()
        for result in results:
            account_number = result.get("accountNumber")
            if account_number is None:
                raise CCHClientServiceError("Invalid CCH client search response")
            normalized = str(account_number).strip()
            if normalized in requested_numbers:
                matches.add(normalized)
        return matches

    def _authorized_headers(self) -> dict[str, str]:
        if self._token is None:
            raise CCHClientServiceError("CCH has not been authenticated")
        return {
            "APIKey": self.settings.cch_axcess_api_key.get_secret_value(),
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{str(self.settings.cch_axcess_url).rstrip('/')}{path}"
