"""Service for Maconomy General Journal operations."""

import base64
import logging
import uuid
from typing import Any
from urllib.parse import quote
import httpx

from app.core.config import Settings, get_settings

LOGGER = logging.getLogger(__name__)

AUTH_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.authentication+json; "
    "charset=utf-8; version=3.0"
)
CONTAINER_ACCEPT = (
    "application/vnd.deltek.maconomy.containers+json; "
    "charset=utf-8; version=9.0"
)
CONTAINER_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.containers+json; "
    "charset=UTF-8; version=9.0"
)

# Standard General Journal card fields
GENERAL_JOURNAL_CARD_FIELDS = [
    "companynumber",
    "journalnumber",
    "period",
    "posted",
    "automaticvouchervar",
    "entrytotalcontrol",
    "description",
    "transactiondate",
]

# Standard General Journal table line fields
GENERAL_JOURNAL_TABLE_FIELDS = [
    "accountnumber",
    "amount",
    "text",
    "entrydate",
    "department",
    "jobnumber",
    "specification1",
    "specification2",
    "specification3",
    "specification4",
]


class MaconomyGeneralJournalServiceError(Exception):
    """Raised when Maconomy General Journal operation fails."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class MaconomyGeneralJournalService:
    """Service to interact with Maconomy General Journal containers."""

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

    def _general_journal_url(self, container_name: str = "generaljournal") -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}"
            f"/maconomy-api/containers/{shortname}/{container_name}"
        )

    def _container_headers(self, reconnect_token: str) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }

    @staticmethod
    def _get_concurrency_token(response: httpx.Response) -> str:
        concurrency = response.headers.get("Maconomy-Concurrency-Control", "").strip()
        if not concurrency:
            raise MaconomyGeneralJournalServiceError(
                "Missing Maconomy-Concurrency-Control header in response",
                status_code=502,
            )
        return concurrency

    async def get_reconnect_token(self, client: httpx.AsyncClient) -> str:
        """Obtain Maconomy X-Reconnect token using Basic credentials."""
        shortname = quote(self.settings.maconomy_shortname, safe="")
        url = f"{self.settings.maconomy_url}/maconomy-api/auth/{shortname}/login"

        credentials = (
            f"{self.settings.maconomy_username}:"
            f"{self.settings.maconomy_password.get_secret_value()}"
        )
        encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode("ascii")

        try:
            response = await client.get(
                url,
                headers={
                    "Accept": AUTH_CONTENT_TYPE,
                    "Maconomy-Authentication": "X-Reconnect",
                    "Authorization": f"Basic {encoded_credentials}",
                },
            )
        except httpx.HTTPError as exc:
            LOGGER.error("Failed to connect to Maconomy auth: %s", exc)
            raise MaconomyGeneralJournalServiceError(
                f"Failed to connect to Maconomy auth: {exc}",
                status_code=502,
            ) from exc

        if response.status_code != 204:
            LOGGER.error(
                "Maconomy authentication failed with status %s: %s",
                response.status_code,
                response.text,
            )
            raise MaconomyGeneralJournalServiceError(
                f"Maconomy authentication failed with status {response.status_code}",
                status_code=response.status_code,
            )

        reconnect_token = response.headers.get("Maconomy-Reconnect", "").strip()
        if not reconnect_token:
            raise MaconomyGeneralJournalServiceError(
                "Missing Maconomy-Reconnect token in response headers",
                status_code=502,
            )

        return reconnect_token

    # -------------------------------------------------------------------------
    # Step 1: Create Container Instance
    # -------------------------------------------------------------------------
    async def create_journal_instance(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        container_name: str = "generaljournal",
        card_fields: list[str] | None = None,
        table_fields: list[str] | None = None,
    ) -> tuple[str, str]:
        """
        Step 1: Retrieve General Journal instance.
        POST /maconomy-api/containers/{shortname}/generaljournal/instances
        Returns: (instance_id, concurrency_token)
        """
        url = f"{self._general_journal_url(container_name)}/instances"
        payload = {
            "panes": {
                "card": {
                    "fields": card_fields or GENERAL_JOURNAL_CARD_FIELDS,
                },
                "table": {
                    "fields": table_fields or GENERAL_JOURNAL_TABLE_FIELDS,
                },
            }
        }

        try:
            response = await client.post(
                url,
                headers=self._container_headers(reconnect_token),
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise MaconomyGeneralJournalServiceError(
                f"Network error creating journal instance: {exc}"
            ) from exc

        if response.is_error:
            LOGGER.error(
                "Maconomy create_journal_instance failed: %s - %s",
                response.status_code,
                response.text,
            )
            raise MaconomyGeneralJournalServiceError(
                f"Failed to create journal instance: {response.text}",
                status_code=response.status_code,
            )

        try:
            instance_id = response.json()["meta"]["containerInstanceId"]
            instance_id = str(uuid.UUID(instance_id))
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyGeneralJournalServiceError(
                "Invalid containerInstanceId in Maconomy response"
            ) from exc

        concurrency_token = self._get_concurrency_token(response)
        return instance_id, concurrency_token

    # -------------------------------------------------------------------------
    # Step 2: Initialize Journal Card
    # -------------------------------------------------------------------------
    async def initialize_journal_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        container_name: str = "generaljournal",
    ) -> tuple[dict[str, Any], str]:
        """
        Step 2: Initialize the journal card.
        POST /maconomy-api/containers/{shortname}/generaljournal/instances/{instance_id}/data/panes/card/init
        Returns: (initialized_card_data, new_concurrency_token)
        """
        url = (
            f"{self._general_journal_url(container_name)}/instances/"
            f"{instance_id}/data/panes/card/init"
        )
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token

        try:
            response = await client.post(url, headers=headers)
        except httpx.HTTPError as exc:
            raise MaconomyGeneralJournalServiceError(
                f"Network error initializing journal card: {exc}"
            ) from exc

        if response.is_error:
            LOGGER.error(
                "Maconomy initialize_journal_card failed: %s - %s",
                response.status_code,
                response.text,
            )
            raise MaconomyGeneralJournalServiceError(
                f"Failed to initialize journal card: {response.text}",
                status_code=response.status_code,
            )

        new_concurrency = self._get_concurrency_token(response)
        return response.json().get("data", {}), new_concurrency

    # -------------------------------------------------------------------------
    # Step 3: Submit Journal Card Header
    # -------------------------------------------------------------------------
    async def submit_journal_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        card_data: dict[str, Any],
        container_name: str = "generaljournal",
    ) -> tuple[dict[str, Any], str]:
        """
        Step 3: Submit the journal card.
        POST /maconomy-api/containers/{shortname}/generaljournal/instances/{instance_id}/data/panes/card
        Returns: (submitted_card_data, new_concurrency_token)
        """
        url = (
            f"{self._general_journal_url(container_name)}/instances/"
            f"{instance_id}/data/panes/card"
        )
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token

        payload = {"data": card_data}

        try:
            response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise MaconomyGeneralJournalServiceError(
                f"Network error submitting journal card: {exc}"
            ) from exc

        if response.is_error:
            LOGGER.error(
                "Maconomy submit_journal_card failed: %s - %s",
                response.status_code,
                response.text,
            )
            raise MaconomyGeneralJournalServiceError(
                f"Failed to submit journal card: {response.text}",
                status_code=response.status_code,
            )

        new_concurrency = self._get_concurrency_token(response)
        return response.json().get("data", {}), new_concurrency

    # -------------------------------------------------------------------------
    # Step 4: Table Lines Initialization & Submission
    # -------------------------------------------------------------------------
    async def initialize_journal_table_line(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        row: str | int = "end",
        container_name: str = "generaljournal",
    ) -> tuple[dict[str, Any], str]:
        """
        Step 4a: Initialize a journal table line.
        POST /maconomy-api/containers/{shortname}/generaljournal/instances/{instance_id}/data/panes/table/init
        Returns: (initialized_line_data, new_concurrency_token)
        """
        url = (
            f"{self._general_journal_url(container_name)}/instances/"
            f"{instance_id}/data/panes/table/init"
        )
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token
        payload = {"row": row}

        try:
            response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise MaconomyGeneralJournalServiceError(
                f"Network error initializing journal line: {exc}"
            ) from exc

        if response.is_error:
            LOGGER.error(
                "Maconomy initialize_journal_table_line failed: %s - %s",
                response.status_code,
                response.text,
            )
            raise MaconomyGeneralJournalServiceError(
                f"Failed to initialize journal line: {response.text}",
                status_code=response.status_code,
            )

        new_concurrency = self._get_concurrency_token(response)
        return response.json().get("data", {}), new_concurrency

    async def submit_journal_table_line(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        line_data: dict[str, Any],
        container_name: str = "generaljournal",
    ) -> tuple[dict[str, Any], str]:
        """
        Step 4b: Submit a journal line item into the table.
        POST /maconomy-api/containers/{shortname}/generaljournal/instances/{instance_id}/data/panes/table
        Returns: (submitted_line_data, new_concurrency_token)
        """
        url = (
            f"{self._general_journal_url(container_name)}/instances/"
            f"{instance_id}/data/panes/table"
        )
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token
        payload = {"data": line_data}

        try:
            response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise MaconomyGeneralJournalServiceError(
                f"Network error submitting journal line: {exc}"
            ) from exc

        if response.is_error:
            LOGGER.error(
                "Maconomy submit_journal_table_line failed: %s - %s",
                response.status_code,
                response.text,
            )
            raise MaconomyGeneralJournalServiceError(
                f"Failed to submit journal line: {response.text}",
                status_code=response.status_code,
            )

        new_concurrency = self._get_concurrency_token(response)
        return response.json().get("data", {}), new_concurrency
