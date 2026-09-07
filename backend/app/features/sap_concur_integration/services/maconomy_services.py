import base64
import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote
from wsgiref import headers

import httpx

from app.core.config import Settings, get_settings
from app.features.sap_concur_integration.mappers import (
    map_concur_expense_report_to_maconomy_expensesheet,
    map_concur_expense_to_maconomy_expense
)

AUTH_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.authentication+json; charset=utf-8; version=3.0"
)
CONTAINER_ACCEPT = (
    "application/vnd.deltek.maconomy.containers+json; charset=utf-8; version=9.0"
)
CONTAINER_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.containers+json; charset=UTF-8; version=9.0"
)


class MaconomyServiceError(Exception):
    pass


class MaconomyService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0


    async def create_expense_sheet(
        self, expense_sheet_data: dict[str, Any]
    ) -> dict[str, Any]:
        print("=========== create_expense_sheet =============")
        try:
            expensesheet_data = map_concur_expense_report_to_maconomy_expensesheet(expense_sheet_data)
        except ValueError as exc:
            raise MaconomyServiceError(str(exc)) from exc

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)

                instance_id, concurrency_token = await self._retrieve_expense_sheet_instance(
                    client=client,
                    reconnect_token=reconnect_token,
                )

                _, concurrency_token = await self._initialize_expense_sheet_card(
                    client=client,
                    reconnect_token=reconnect_token,
                    instance_id=instance_id,
                    concurrency_token=concurrency_token,
                )


                print("======== Expense Sheet Creation Started ========")
                url = f"{self._expense_sheet_url()}/instances/{instance_id}/data/panes/card"
                headers = self._container_headers(reconnect_token)
                headers["Maconomy-Concurrency-Control"] = concurrency_token
                response = await client.post(url, headers=headers, json=expensesheet_data)

                response.raise_for_status()

                try:
                    payload = response.json()
                except (KeyError, TypeError, ValueError) as exc:
                    raise MaconomyServiceError("Invalid Maconomy expense sheet response") from exc
        
                if not isinstance(payload, dict):
                    raise MaconomyServiceError(
                        "Invalid Maconomy expense sheet response"
                    )

                print("========= Expense Sheet creation completed ==========")
                return payload
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy request failed") from exc


    async def _get_reconnect_token(self, client: httpx.AsyncClient) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        url = f"{self.settings.maconomy_url}/maconomy-api/auth/{shortname}/login"
        credentials = (
            f"{self.settings.maconomy_username}:"
            f"{self.settings.maconomy_password.get_secret_value()}"
        )
        encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode(
            "ascii"
        )

        response = await client.get(
            url,
            headers={
                "Accept": AUTH_CONTENT_TYPE,
                "Maconomy-Authentication": "X-Reconnect",
                "Authorization": f"Basic {encoded_credentials}",
            },
        )
        response.raise_for_status()

        token = response.headers.get("Maconomy-Reconnect", "").strip()

        if response.status_code != 204 or not token:
            raise MaconomyServiceError("Maconomy authentication failed")
        return token


    def _expense_sheet_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return f"{self.settings.maconomy_url}/maconomy-api/containers/{shortname}/expensesheets"


    @staticmethod
    def _container_headers(reconnect_token: str) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }


    # Check with Maconomy if the expense sheet exists by expense sheet number
    async def get_expensesheet_by_expensesheetnumber(self, expensesheet_number: str) -> dict[str, Any] | None: 
        if not expensesheet_number.strip():
            raise MaconomyServiceError("Invalid expense sheet number")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)
                url = f"{self._expense_sheet_url()}/filter"
                payload = {
                    "panes": {
                        "card": {
                            "fields": [
                                "amountbase",
                                "basecurrency",
                                "createddate",
                                "datesubmitted",
                                "employeename",
                                "employeenumber",
                                "expensesheetnumber",
                                "jobname",
                                "jobnumber"
                            ]
                        }
                    }
                }
                headers = self._container_headers(reconnect_token)
                response = await client.get(url, headers=headers, params=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MaconomyServiceError(
                "Unable to reconcile entity in CaseWare Cloud"
            ) from exc
        
        try:
            payload = response.json()
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy expense sheet response") from exc

        if not isinstance(payload, dict):
            raise MaconomyServiceError(
                "Invalid Maconomy expense sheet response"
            )

        card = response.json()["panes"]["card"]
        records = card["records"]

        if not isinstance(records, list):
            raise MaconomyServiceError(
                "Invalid Maconomy expense sheet response: invalid records"
            )

        matching_expense_sheets = []

        for record in records:
            if not isinstance(record, dict):
                continue

            data = record.get("data")

            if not isinstance(data, dict):
                continue

            if data.get("expenseSheetNumber") == expensesheet_number:
                matching_expense_sheets.append(data)

        if not matching_expense_sheets:
            return None

        if len(matching_expense_sheets) > 1:
            raise MaconomyServiceError(
                "Maconomy reconciliation is ambiguous and requires "
                "manual resolution"
            )

        return matching_expense_sheets[0]


    # Retrieve instance key from maconomy for expense sheet container 
    async def _retrieve_expense_sheet_instance(
            self,
            client: httpx.AsyncClient,
            reconnect_token: str,
        ) -> tuple[str, str]:
            url = f"{self._expense_sheet_url()}/instances"

            payload = {"panes":{"card":{"fields":["description"]},"table":{"fields":[]}}}

            print("======= _retrieve_expense_sheet_instance ==========")
            response = await client.post(
                url,
                headers=self._container_headers(
                    reconnect_token
                ),
                json=payload,
            )
            response.raise_for_status()

            try:
                instance_id = response.json()["meta"][
                    "containerInstanceId"
                ]
                instance_id = str(uuid.UUID(instance_id))
    
            except (KeyError, TypeError, ValueError) as exc:
                raise MaconomyServiceError(
                    "Invalid Maconomy employee instance response"
                ) from exc
    
            concurrency_token = self._get_concurrency_token(
                response
            )
    
            return instance_id, concurrency_token


    # Initialize the expense sheet container with the required fields
    async def _initialize_expense_sheet_card(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
    ) -> tuple[dict[str, Any], str]:
        url = (
            f"{self._expense_sheet_url()}/instances/"
            f"{instance_id}/data/panes/card/init"
        )
 
        headers = self._container_headers(
            reconnect_token
        )
        headers["Maconomy-Concurrency-Control"] = (
            concurrency_token
        )
        print("========= _initialize_expense_sheet_card =========")
        response = await client.post(
            url,
            headers=headers,
            json={},
        )

        response.raise_for_status()
 
        try:
            initialized_data = response.json()["data"]
 
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy employee initialization response"
            ) from exc
 
        if not isinstance(initialized_data, dict):
            raise MaconomyServiceError(
                "Invalid Maconomy employee initialization response"
            )
 
        # instance_key = response.json["meta"].get("containerInstanceId")
 
        # if (
        #     not isinstance(instance_key, str)
        #     or not instance_key.strip()
        # ):
        #     raise MaconomyServiceError(
        #         "Maconomy expense sheet instance key is missing"
        #     )
 
        new_concurrency_token = self._get_concurrency_token(
            response
        )
        print("Card initialized!")
        return dict(initialized_data), new_concurrency_token


    @staticmethod
    def _get_concurrency_token(
        response: httpx.Response,
    ) -> str:
        concurrency_token = response.headers.get(
            "Maconomy-Concurrency-Control",
            "",
        ).strip()
 
        try:
            return str(uuid.UUID(concurrency_token))
 
        except (TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy concurrency token"
            ) from exc
 






