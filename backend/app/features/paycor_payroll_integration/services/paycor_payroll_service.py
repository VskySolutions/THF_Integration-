"""Service for interacting with Paycor Payroll API."""

import logging
from typing import Any
import httpx

from app.core.config import Settings, get_settings

LOGGER = logging.getLogger(__name__)


class PaycorPayrollServiceError(Exception):
    """Raised when Paycor Payroll API calls fail."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class PaycorPayrollService:
    """Handles Paycor OAuth authentication and Payroll endpoints."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._external_client = client
        self.timeout = 60.0

    @property
    def base_url(self) -> str:
        """Get Paycor base URL (prefers LIVE)."""
        if self.settings.paycor_base_url_live:
            return str(self.settings.paycor_base_url_live).rstrip("/")
        return str(self.settings.paycor_base_url).rstrip("/")

    @property
    def client_id(self) -> str:
        """Get Paycor client ID (prefers LIVE)."""
        if self.settings.paycor_client_id_live:
            return self.settings.paycor_client_id_live.get_secret_value().strip()
        return self.settings.paycor_client_id.get_secret_value().strip()

    @property
    def client_secret(self) -> str:
        """Get Paycor client secret (prefers LIVE, strips any 'Secret :' prefix)."""
        if self.settings.paycor_client_secret_live:
            raw = self.settings.paycor_client_secret_live.get_secret_value()
        else:
            raw = self.settings.paycor_client_secret.get_secret_value()
        # Clean up any potential 'Secret :' copy-paste prefix
        if "Secret :" in raw:
            raw = raw.split("Secret :")[-1]
        elif "Secret:" in raw:
            raw = raw.split("Secret:")[-1]
        return raw.strip()

    @property
    def refresh_token(self) -> str:
        """Get Paycor refresh token (prefers LIVE)."""
        if self.settings.paycor_refresh_token_live:
            return self.settings.paycor_refresh_token_live.get_secret_value().strip()
        return self.settings.paycor_refresh_token.get_secret_value().strip()

    @property
    def subscription_key(self) -> str:
        """Get Paycor subscription key (prefers LIVE)."""
        if self.settings.paycor_subscription_key_live:
            return self.settings.paycor_subscription_key_live.get_secret_value().strip()
        return self.settings.paycor_subscription_key.get_secret_value().strip()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(timeout=self.timeout)

    async def get_access_token(self, client: httpx.AsyncClient) -> str:
        """Obtain OAuth access token from Paycor STS using refresh token."""
        token_url = f"{self.base_url}/sts/v1/common/token"
        params = {
            "subscription-key": self.subscription_key,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }

        try:
            response = await client.post(
                token_url,
                params=params,
                headers=headers,
                data=data,
            )
        except httpx.HTTPError as exc:
            LOGGER.error("Failed to connect to Paycor STS for access token: %s", exc)
            raise PaycorPayrollServiceError(
                f"Failed to connect to Paycor STS: {exc}",
                status_code=502,
            ) from exc

        if response.is_error:
            LOGGER.error(
                "Paycor STS token request failed: %s - %s",
                response.status_code,
                response.text,
            )
            raise PaycorPayrollServiceError(
                f"Paycor token request failed with status {response.status_code}: {response.text}",
                status_code=response.status_code,
            )

        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise PaycorPayrollServiceError(
                "Paycor STS response missing access_token",
                status_code=502,
            )
        return access_token

    async def get_payroll_processing(
        self,
        legal_entity_id: int | str,
        from_check_date: str | None = None,
        to_check_date: str | None = None,
        include_other_payruns: str = "All",
        continuation_token: str | None = None,
    ) -> dict[str, Any]:
        """Fetch payroll processing data for a legal entity within a check date range."""
        from app.features.paycor_payroll_integration.mappers.payroll_journal_mapper import format_iso_datetime

        client = await self._get_client()
        should_close = self._external_client is None

        # Ensure dynamic live default ISO format: YYYY-MM-DDTHH:MM:SS
        formatted_from_date = format_iso_datetime(from_check_date)

        try:
            access_token = await self.get_access_token(client)
            url = (
                f"{self.base_url}/v1/legalentities/"
                f"{legal_entity_id}/payrollProcessing"
            )

            params: dict[str, Any] = {
                "fromCheckDate": formatted_from_date,
                "includeOtherPayruns": include_other_payruns or "All",
            }
            if to_check_date:
                params["toCheckDate"] = format_iso_datetime(to_check_date)
            if continuation_token:
                params["continuationToken"] = continuation_token

            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
                "Ocp-Apim-Subscription-Key": self.subscription_key,
            }

            response = await client.get(
                url,
                headers=headers,
                params=params,
            )

            if response.is_error:
                LOGGER.error(
                    "Paycor payrollProcessing request failed: %s - %s",
                    response.status_code,
                    response.text,
                )
                raise PaycorPayrollServiceError(
                    message=response.text,
                    status_code=response.status_code,
                )

            return response.json()

        except httpx.HTTPError as exc:
            LOGGER.error("Paycor payrollProcessing HTTP communication failure: %s", exc)
            raise PaycorPayrollServiceError(
                f"Paycor API request failed: {exc}",
                status_code=502,
            ) from exc
        finally:
            if should_close:
                await client.aclose()

    async def get_general_ledger_with_employee(
        self,
        legal_entity_id: int | str,
        planner_id: str,
        continuation_token: str | None = None,
        client: httpx.AsyncClient | None = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """Fetch general ledger with employee data for a specific plannerId."""
        passed_client = client is not None
        http_client = client if client is not None else await self._get_client()
        should_close = not passed_client and self._external_client is None

        try:
            if not access_token:
                access_token = await self.get_access_token(http_client)

            url = (
                f"{self.base_url}/v1/legalentities/"
                f"{legal_entity_id}/generalledgerwithemployee"
            )

            params: dict[str, Any] = {
                "plannerId": planner_id,
            }
            if continuation_token:
                params["continuationToken"] = continuation_token

            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
                "Ocp-Apim-Subscription-Key": self.subscription_key,
            }

            response = await http_client.get(
                url,
                headers=headers,
                params=params,
            )

            if response.is_error:
                LOGGER.error(
                    "Paycor generalLedgerWithEmployee request failed for plannerId %s: %s - %s",
                    planner_id,
                    response.status_code,
                    response.text,
                )
                raise PaycorPayrollServiceError(
                    message=response.text,
                    status_code=response.status_code,
                )

            return response.json()

        except httpx.HTTPError as exc:
            LOGGER.error(
                "Paycor generalLedgerWithEmployee HTTP communication failure for plannerId %s: %s",
                planner_id,
                exc,
            )
            raise PaycorPayrollServiceError(
                f"Paycor API request failed: {exc}",
                status_code=502,
            ) from exc
        finally:
            if should_close:
                await http_client.aclose()

    async def get_legal_entity_employees(
        self,
        legal_entity_id: int | str,
        continuation_token: str | None = None,
        client: httpx.AsyncClient | None = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """Fetch employees for a legal entity (PH1)."""
        passed_client = client is not None
        http_client = client if client is not None else await self._get_client()
        should_close = not passed_client and self._external_client is None

        try:
            if not access_token:
                access_token = await self.get_access_token(http_client)

            url = f"{self.base_url}/v1/legalentities/{legal_entity_id}/employees"
            params: dict[str, Any] = {}
            if continuation_token:
                params["continuationToken"] = continuation_token

            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
                "Ocp-Apim-Subscription-Key": self.subscription_key,
            }

            response = await http_client.get(
                url,
                headers=headers,
                params=params,
            )

            if response.is_error:
                LOGGER.error(
                    "Paycor get_legal_entity_employees request failed for legalEntityId %s: %s - %s",
                    legal_entity_id,
                    response.status_code,
                    response.text,
                )
                raise PaycorPayrollServiceError(
                    message=response.text,
                    status_code=response.status_code,
                )

            return response.json()

        except httpx.HTTPError as exc:
            LOGGER.error(
                "Paycor get_legal_entity_employees HTTP communication failure for legalEntityId %s: %s",
                legal_entity_id,
                exc,
            )
            raise PaycorPayrollServiceError(
                f"Paycor API request failed: {exc}",
                status_code=502,
            ) from exc
        finally:
            if should_close:
                await http_client.aclose()

    async def get_employee_number_lookup(
        self,
        legal_entity_id: int | str,
        client: httpx.AsyncClient | None = None,
        access_token: str | None = None,
    ) -> dict[str, str]:
        """
        Build an in-memory lookup map of employeeId -> employeeNumber (PH1).
        Supports pagination if more pages are returned.
        """
        passed_client = client is not None
        http_client = client if client is not None else await self._get_client()
        should_close = not passed_client and self._external_client is None

        lookup: dict[str, str] = {}
        continuation_token: str | None = None

        try:
            if not access_token:
                access_token = await self.get_access_token(http_client)

            # Paginate through employees if continuationToken exists
            max_pages = 20
            for _ in range(max_pages):
                data = await self.get_legal_entity_employees(
                    legal_entity_id=legal_entity_id,
                    continuation_token=continuation_token,
                    client=http_client,
                    access_token=access_token,
                )

                records = (
                    data.get("records", [])
                    if isinstance(data, dict) and "records" in data
                    else data
                    if isinstance(data, list)
                    else []
                )

                for emp in records:
                    if not isinstance(emp, dict):
                        continue
                    emp_id = (
                        emp.get("employeeId")
                        or emp.get("id")
                        or emp.get("employeeID")
                    )
                    emp_num = (
                        emp.get("employeeNumber")
                        or emp.get("employee_number")
                        or emp.get("employeeNum")
                    )
                    if emp_id and emp_num:
                        lookup[str(emp_id).strip()] = str(emp_num).strip()

                continuation_token = (
                    data.get("continuationToken")
                    if isinstance(data, dict)
                    else None
                )
                if not continuation_token:
                    break

            return lookup

        except Exception as exc:
            LOGGER.warning(
                "Could not build complete employee number lookup for legalEntityId %s: %s",
                legal_entity_id,
                exc,
            )
            return lookup
        finally:
            if should_close:
                await http_client.aclose()

    async def get_employee_work_location_lookup(
        self,
        legal_entity_id: int | str,
        client: httpx.AsyncClient | None = None,
        access_token: str | None = None,
    ) -> dict[str, str]:
        """
        Build lookup map of departmentId -> workLocationName (Maconomy specification4name).
        Returns the static dictionary mapping Paycor Department UUID to location names (Tampa, Tallahassee, etc.).
        """
        from app.features.paycor_payroll_integration.constants import STATIC_DEPARTMENT_WORK_LOCATIONS
        return STATIC_DEPARTMENT_WORK_LOCATIONS


