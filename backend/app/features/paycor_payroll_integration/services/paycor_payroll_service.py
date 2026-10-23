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

    async def _get_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(timeout=self.timeout)

    async def get_access_token(self, client: httpx.AsyncClient) -> str:
        """Obtain OAuth access token from Paycor STS using refresh token."""
        token_url = f"{str(self.settings.paycor_base_url).rstrip('/')}/sts/v1/common/token"
        params = {
            "subscription-key": self.settings.paycor_subscription_key.get_secret_value(),
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "refresh_token",
            "client_id": self.settings.paycor_client_id.get_secret_value(),
            "client_secret": self.settings.paycor_client_secret.get_secret_value(),
            "refresh_token": self.settings.paycor_refresh_token.get_secret_value(),
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
                f"{str(self.settings.paycor_base_url).rstrip('/')}/v1/legalentities/"
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
                "Ocp-Apim-Subscription-Key": self.settings.paycor_subscription_key.get_secret_value(),
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
                f"{str(self.settings.paycor_base_url).rstrip('/')}/v1/legalentities/"
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
                "Ocp-Apim-Subscription-Key": self.settings.paycor_subscription_key.get_secret_value(),
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
