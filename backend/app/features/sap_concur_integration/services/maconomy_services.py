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
from app.features.sap_concur_integration.services.sap_concur_service import SAPConcurService

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

    def extract_job_number_from_client_engagement(self, value: str) -> str:
        """
        Extract job number from Client Engagement value.
        Example: "(75674.T0) 1130 SUCCESS AVE LLC" -> "75674"
        """
        import re
        match = re.search(r'\(([^.]+)\.', value)
        if match:
            return match.group(1)
        return value


    async def create_expense_sheet(
        self, expense_sheet_data: dict[str, Any], employee_number: str | None = None
    ) -> dict[str, Any]:
        print("=========== create_expense_sheet =============")
        try:
            expensesheet_data = map_concur_expense_report_to_maconomy_expensesheet(
                expense_sheet_data, employee_number=employee_number
            )
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
                except (KeyError, TypeError, ValueError) as json_exc:
                    raise MaconomyServiceError("Invalid Maconomy expense sheet response") from json_exc
        
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

            payload = {"panes":{"card":{"fields":["description","employeenumber","expensesheettext5"]},"table":{"fields":[]}}}

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
 

    async def get_expensesheet_by_expensesheetnumber(
        self, maconomy_expensesheet_no: str
    ) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)
                instance_id, concurrency_token = await self._start_expensesheet_lookup(
                    client, reconnect_token
                )
                return await self._get_expensesheet_record(
                    client,
                    reconnect_token,
                    instance_id,
                    concurrency_token,
                    maconomy_expensesheet_no,
                )
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy request failed") from exc


    async def _start_expensesheet_lookup(
        self, client: httpx.AsyncClient, reconnect_token: str
    ) -> tuple[str, str]:
        url = f"{self._expense_sheet_url()}/instances"
        payload = {
            "panes": {
                "card": {
                    "fields": [
                        "expensesheetnumber",
                        "description",
                        # "name1",
                        # "name2",
                        # "name3",
                        # "name4",
                        # "postaldistrict",
                        # "country",
                        # "customernumber",
                        # "template",
                        # "versionnumber"
                    ]
                }
            }
        }
        response = await client.post(
            url,
            headers=self._container_headers(reconnect_token),
            json=payload,
        )

        response.raise_for_status()
        concurrency_token = response.headers.get("Maconomy-Concurrency-Control", "")
        try:
            instance_id = response.json()["meta"]["containerInstanceId"]
            instance_id = str(uuid.UUID(instance_id))
            concurrency_token = str(uuid.UUID(concurrency_token))
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy instance response") from exc

        return instance_id, concurrency_token


    async def _get_expensesheet_record(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        maconomy_expensesheet_no: str,
    ) -> dict[str, Any] | None:
        maconomy_expensesheet_no = quote(maconomy_expensesheet_no, safe="")
        url = f"{self._jobs_url()}/instances/{instance_id}/data;expensesheetnumber={maconomy_expensesheet_no}"
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token

        response = await client.post(url, headers=headers, json={})
        response.raise_for_status()

        try:
            card = response.json()["panes"]["card"]
            records = card["records"]
            if card["meta"]["rowCount"] != 1 or len(records) != 1:
                return None
            expensesheet_data = records[0]["data"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy job response") from exc

        if not isinstance(expensesheet_data, dict):
            raise MaconomyServiceError("Invalid Maconomy job response")
        return expensesheet_data


    async def get_all_employees_from_maconomy(
            self,
        ) -> list[dict[str, Any]]:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    reconnect_token = await self._get_reconnect_token(client)
                    return await self._get_maconomy_employees(
                        client,
                        reconnect_token,
                    )
            except httpx.HTTPError as exc:
                raise MaconomyServiceError("Maconomy request failed") from exc


    async def _get_maconomy_employees(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    )-> dict[str, Any] | None:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        
        url = f"{self.settings.maconomy_url}/maconomy-api/containers/{shortname}/showemployeeshr/filter"
        
        payload = {
            "restriction":"DateEmployed le currentDate() and (DateEndEmployment gt currentDate() or DateEndEmployment = date(nulldate))",
            "fields":["companyname","companynumber","country","vendornumber","departmentnumber","electronicmailaddress","employeenumber","employeetype","instancekey","name1","position","superioremployee"],
            "limit":500
        }

        response = await client.post(
            url,
            headers=self._container_headers(
                reconnect_token
            ),
            json=payload,
        )
        response.raise_for_status()


        try:
            employee_card = response.json()["panes"]["filter"]["records"]
            # records = employee_card["records"]
            # if employee_card["meta"]["rowCount"] != 1 or len(records) != 1:
            #     return None
            # job_data = records[0]["data"]

            filtered_employees = [
                {
                    "employeenumber": item["data"]["employeenumber"], 
                    "vendornumber": item["data"]["vendornumber"],
                    "email": item["data"]["electronicmailaddress"],
                    "employeename": item["data"]["name1"],
                    "instancekey": item["data"]["instancekey"]
                }
                for item in employee_card
                if item["data"]["electronicmailaddress"] # and item["data"]["vendornumber"]
            ]


        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid employee response") from exc

        # if not isinstance(job_data, dict):
        #     raise MaconomyServiceError("Invalid Maconomy job response")
        print(len(filtered_employees))
        return filtered_employees


    # Maconomy Expenses

    # Expense Line Items
    async def _retrieve_expenses_instance(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> tuple[str, str]:
        url = f"{self._expense_sheet_url()}/instances"

        payload = {"panes":{"card":{"fields":["description","employeenumber","expensesheettext5"]},"table":{"fields":["entrydate","expensesheetlinetext10","currency","linenumber","numberof","unitpricecurrency","specification4name","entityname","text","jobnumber","taskname"]}}} # "specification4name","locationname","amountbase", "specification4name"

        print("======= _retrieve_expense_instance ==========")
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

    
    async def _initialize_expense_table(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        row: int,
    ) -> tuple[dict[str, Any], str]:
        print("instance_id:", instance_id)
        url = (
            f"{self._expense_sheet_url()}/instances/"
            f"{instance_id}/data/panes/table/init"
        )
 
        headers = self._container_headers(
            reconnect_token
        )
        headers["Maconomy-Concurrency-Control"] = (
            concurrency_token
        )
        payload={"row":"end"}
        print("========= _initialize_expense_table =========")
        response = await client.post(
            url,
            headers=headers,
            json=payload,
        )
        print("Expense line response:", response.status_code, response.text)
 
        response.raise_for_status()
 
        try:
            initialized_data = response.json()["data"]
 
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                "Invalid Maconomy Expense line initialization response"
            ) from exc
 
        if not isinstance(initialized_data, dict):
            raise MaconomyServiceError(
                "Invalid Maconomy Expense line initialization response"
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
        print("Table initialized!")
        return dict(initialized_data), new_concurrency_token


    async def create_expense_line_items(
        self,
        expense_sheet_number: str,
        expense_data: list[dict[str, Any]],
        employee_number: str | None = None,
        report_id: str | None = None,
        user_id: str | None = None,
        context_type: str | None = None,
    ) -> dict[str, Any]:
        """Create Maconomy expense lines fault-tolerantly.

        Each expense line is processed independently through its own
        fetch -> resolve customData -> map -> create pipeline. A failure on
        one line is captured (original exception text retained) and
        processing CONTINUES with the remaining lines — a single failed
        line never terminates the report.

        Shared Maconomy session setup (client + reconnect token) is a
        report-level concern: if setup fails, MaconomyServiceError is
        raised as before.

        Returns:
            {
                "succeeded": [{"expense_id", "line_number", "response"}, ...],
                "failed": [{"expense_id", "error_type", "message"}, ...],
                "total": int,
                "success_count": int,
                "failure_count": int,
            }
            Skips (missing expenseId / detail not found / list item not
            found) are recorded in "failed" with error_type "SKIPPED".
        """
        print("=========== create_expense_line_items =============")

        sap_concur_service = SAPConcurService()
        succeeded: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        def _record_skip(expense_id: str | None, reason: str) -> None:
            print(f"Skipping expense: {reason}")
            failed.append(
                {
                    "expense_id": expense_id or "",
                    "error_type": "SKIPPED",
                    "message": reason,
                }
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # --- Report-level setup (raises on failure, as today) ---
                try:
                    reconnect_token = await self._get_reconnect_token(client)
                except httpx.HTTPError as exc:
                    raise MaconomyServiceError("Maconomy request failed") from exc

                print("======== Expense Line Items Creation Started ========")

                # --- Per-line pipeline: one failure never stops the rest ---
                for index, expense_item in enumerate(expense_data):
                    expense_id = expense_item.get("expenseId")
                    try:
                        if not expense_id:
                            _record_skip(None, "missing expenseId")
                            continue

                        print(
                            f"---- Processing expense line {index} "
                            f"(expense_id={expense_id}) ----"
                        )

                        # 1) Fetch detailed expense data from SAP Concur
                        detailed_expense = (
                            await sap_concur_service.get_expenses_by_expense_id(
                                expense_id=expense_id,
                                report_id=report_id or "",
                                user_id=user_id or "",
                                context_type=context_type or "",
                            )
                        )
                        if detailed_expense is None:
                            _record_skip(
                                str(expense_id),
                                "could not retrieve detailed data for "
                                f"expense_id={expense_id}",
                            )
                            continue

                        # 2) Resolve customData list items
                        custom_data = detailed_expense.get("customData", [])
                        print("=== custom_data ===:", custom_data)
                        custom_data_values: dict[str, Any] = {}
                        skip_expense = False
                        skip_reason = ""

                        if custom_data:
                            for custom_entry in custom_data:
                                print("custom_entry:", custom_entry)
                                entry_id = custom_entry.get("id")
                                entry_value = custom_entry.get("value", "")

                                if not entry_id:
                                    continue

                                # Only process custom1, custom2, custom5, custom6
                                if entry_id not in (
                                    "custom1",
                                    "custom2",
                                    "custom5",
                                    "custom6",
                                ):
                                    continue

                                list_item = (
                                    await sap_concur_service.get_list_items_by_id(
                                        report_id=report_id or "",
                                        user_id=user_id or "",
                                        context_type=context_type or "",
                                        item_id=entry_value,
                                    )
                                )

                                if list_item is None:
                                    skip_reason = (
                                        "get_list_items_by_id returned None "
                                        f"for {entry_id}={entry_value}"
                                    )
                                    skip_expense = True
                                    break

                                if entry_id == "custom1":
                                    # Location
                                    custom_data_values["location"] = (
                                        list_item.get("value", "")
                                    )
                                elif entry_id == "custom2":
                                    # Department
                                    custom_data_values["department"] = (
                                        list_item.get("value", "")
                                    )
                                elif entry_id == "custom5":
                                    # Travel Reason
                                    custom_data_values["travel_reason"] = (
                                        list_item.get("value", "")
                                    )
                                elif entry_id == "custom6":
                                    # Client Engagement - extract job number
                                    client_engagement = list_item.get("value", "")
                                    custom_data_values["client_engagement"] = (
                                        client_engagement
                                    )
                                    custom_data_values["job_number"] = (
                                        self.extract_job_number_from_client_engagement(
                                            client_engagement
                                        )
                                    )

                        if skip_expense:
                            _record_skip(str(expense_id), skip_reason)
                            continue

                        detailed_expense["_custom_data_values"] = (
                            custom_data_values
                        )

                        # 3) Map THIS line only — one ValueError no longer
                        #    aborts the batch
                        expense_line_data = map_concur_expense_to_maconomy_expense(
                            detailed_expense,
                            expense_sheet_number=expense_sheet_number,
                            employee_number=employee_number,
                            custom_data_values=custom_data_values,
                        )

                        # 4) Create the line in Maconomy — exact existing
                        #    per-line call sequence preserved
                        instance_id, concurrency_token = (
                            await self._retrieve_expenses_instance(
                                client=client,
                                reconnect_token=reconnect_token,
                            )
                        )

                        # Load existing expense sheet into the container
                        load_url = (
                            f"{self._expense_sheet_url()}/instances/"
                            f"{instance_id}/data;expensesheetnumber="
                            f"{quote(expense_sheet_number, safe='')}"
                        )
                        load_headers = self._container_headers(reconnect_token)
                        load_headers["Maconomy-Concurrency-Control"] = (
                            concurrency_token
                        )
                        load_response = await client.post(
                            load_url, headers=load_headers, json={}
                        )
                        load_response.raise_for_status()
                        concurrency_token = self._get_concurrency_token(
                            load_response
                        )

                        _, concurrency_token = (
                            await self._initialize_expense_table(
                                client=client,
                                reconnect_token=reconnect_token,
                                instance_id=instance_id,
                                concurrency_token=concurrency_token,
                                row=index + 1,
                            )
                        )

                        url = (
                            f"{self._expense_sheet_url()}/instances/"
                            f"{instance_id}/data/panes/table"
                        )
                        headers = self._container_headers(reconnect_token)
                        headers["Maconomy-Concurrency-Control"] = (
                            concurrency_token
                        )
                        print("expense_line_data:", expense_line_data)
                        response = await client.post(
                            url, headers=headers, json=expense_line_data
                        )
                        print("response:", response.status_code, response.text)
                        response.raise_for_status()

                        try:
                            payload = response.json()
                        except (KeyError, TypeError, ValueError) as json_exc:
                            raise MaconomyServiceError(
                                f"Invalid Maconomy expense line response "
                                f"for line {index}"
                            ) from json_exc

                        if not isinstance(payload, dict):
                            raise MaconomyServiceError(
                                f"Invalid Maconomy expense line response "
                                f"for line {index}"
                            )

                        # Extract line number (same shape the router uses)
                        line_number = ""
                        try:
                            records = (
                                payload.get("panes", {})
                                .get("table", {})
                                .get("records", [])
                            )
                            if records:
                                line_number = str(
                                    records[-1]
                                    .get("data", {})
                                    .get("linenumber", "")
                                )
                        except (KeyError, TypeError, IndexError):
                            line_number = ""

                        succeeded.append(
                            {
                                "expense_id": str(expense_id),
                                "line_number": line_number,
                                "response": payload,
                            }
                        )

                    except Exception as exc:
                        # Line-scoped failure: capture original exception and
                        # CONTINUE with the next line. Never re-raise here.
                        print(
                            f"Expense line failed "
                            f"(expense_id={expense_id}): {exc}"
                        )
                        failed.append(
                            {
                                "expense_id": str(expense_id)
                                if expense_id
                                else "",
                                "error_type": type(exc).__name__,
                                "message": str(exc),
                            }
                        )
                        continue

                print("========= Expense Line Items creation completed ==========")

        except MaconomyServiceError:
            raise
        except httpx.HTTPError as exc:
            # Only reachable from report-level setup outside the per-line guard
            raise MaconomyServiceError("Maconomy request failed") from exc

        return {
            "succeeded": succeeded,
            "failed": failed,
            "total": len(expense_data),
            "success_count": len(succeeded),
            "failure_count": len(failed),
        }
        



# ==================== Get all expense sheets from Maconomy ====================
    async def get_all_expense_sheets_from_maconomy(
            self,
        ) -> list[dict[str, Any]]:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    reconnect_token = await self._get_reconnect_token(client)
                    return await self._get_maconomy_expense_sheets(
                        client,
                        reconnect_token,
                    )
            except httpx.HTTPError as exc:
                raise MaconomyServiceError("Maconomy request failed") from exc


    async def _get_maconomy_expense_sheets(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    )-> dict[str, Any] | None:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        
        url = f"{self.settings.maconomy_url}/maconomy-api/containers/{shortname}/expensesheets/filter"
        
        payload = {
            "fields":["amountbase","approvaldate","approved","createddate","description","employeename","employeenumber","expensesheetnumber","expensesheettext5","fullyapproved","instancekey","submitted","vendorsettlementstatus"],
            "limit":500,
        }

        response = await client.post(
            url,
            headers=self._container_headers(
                reconnect_token
            ),
            json=payload,
        )
        response.raise_for_status()
        print("response:",response)


        try:
            expensesheets = response.json()["panes"]["filter"]["records"]
            # records = employee_card["records"]
            # if employee_card["meta"]["rowCount"] != 1 or len(records) != 1:
            #     return None
            # job_data = records[0]["data"]

            filtered_expensesheets = [
                {
                    "expensesheetnumber": item["data"]["expensesheetnumber"], 
                    "employeenumber": item["data"]["employeenumber"],
                    "instancekey": item["data"]["instancekey"],
                    "sap_report_id": item["data"]["expensesheettext5"]
                }
                for item in expensesheets
                if item["data"]["expensesheetnumber"] and item["data"]["expensesheettext5"]
            ]


        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid vendor response", exc) from exc

        # if not isinstance(job_data, dict):
        #     raise MaconomyServiceError("Invalid Maconomy job response")
        print(len(filtered_expensesheets))
        return filtered_expensesheets


