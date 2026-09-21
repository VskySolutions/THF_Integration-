from datetime import datetime, timedelta

from typing import Any

import httpx

from app.core.config import Settings, get_settings


class SAPConcurServiceError(Exception):
    pass


class SAPConcurEntityCreationError(SAPConcurServiceError):
    def __init__(self, message: str, *, reconciliation_allowed: bool) -> None:
        super().__init__(message)
        self.reconciliation_allowed = reconciliation_allowed


class SAPConcurService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0


    #  Get report details using report_id V4 API
    async def get_report_by_id(
        self,
        report_id: str,
        user_id: str,
        context_type: str,
    ) -> dict[str, Any] | None:
        print(f"Fetching report details for report_id: {report_id}, user_id: {user_id}, context_type: {context_type}")
        if not report_id.strip():
            raise SAPConcurServiceError("Invalid Concur Expense report ID")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token_from_refresh_token(client)
                response = await client.get(
                    f"{self.settings.sap_concur_api_base_url}/expensereports/v4/users/{user_id}/context/{context_type}/reports/{report_id}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                if response.status_code == httpx.codes.NOT_FOUND:
                    return None
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError(
                "Unable to reconcile report in Concur"
            ) from exc

        try:
            report = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid Concur report response"
            ) from exc

        if not isinstance(report, dict):
            raise SAPConcurServiceError(
                "Invalid Concur report response"
            )

        exp_report_id = report["reportId"]
        report_name = report["name"]
        if (
            not isinstance(exp_report_id, str)
            or not exp_report_id.strip()
            or not isinstance(report_name, str)
        ):
            raise SAPConcurServiceError(
                "Invalid Concur report response"
            )

        return report


    # Get expenses aligned with the report
    async def get_expenses_by_report_id(
        self,
        report_id: str,
        user_id: str,
        context_type: str,
    ) -> list[dict[str, Any]]:
        if not report_id.strip():
            raise SAPConcurServiceError("Invalid Concur report ID")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token_from_refresh_token(client)
                response = await client.get(
                    f"{self.settings.sap_concur_api_base_url}/expensereports/v4/users/{user_id}/context/{context_type}/reports/{report_id}/expenses",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                if response.status_code == httpx.codes.NOT_FOUND:
                    raise SAPConcurServiceError(
                        f"Concur report '{report_id}' not found"
                    )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError(
                "Unable to retrieve expenses from Concur"
            ) from exc

        try:
            expenses = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid Concur expenses response"
            ) from exc

        if not isinstance(expenses, list) or any(
            not isinstance(expense, dict) for expense in expenses
        ):
            raise SAPConcurServiceError(
                "Invalid Concur expenses response"
            )

        for expense in expenses:
            expense_id = expense.get("expenseId")
            # amount = expense.get("Amount")
            if (
                not isinstance(expense_id, str)
                or not expense_id.strip()
                # or not isinstance(amount, (int, float))
                # or isinstance(amount, bool)
            ):
                raise SAPConcurServiceError(
                    "Invalid Concur expenses response"
                )

        return expenses


    # Get detailed expense data by expense_id (includes customData)
    async def get_expenses_by_expense_id(
        self,
        expense_id: str,
        report_id: str,
        user_id: str,
        context_type: str,
    ) -> dict[str, Any] | None:
        """
        Retrieve complete detailed expense data for a specific expense by expense_id.
        
        This endpoint returns ALL expense details including:
        - All standard expense fields (expenseType, transactionDate, amount, etc.)
        - customData array with custom1, custom2, custom5, custom6
        
        This data should be used for:
        - Expense mapping to Maconomy format
        - Custom data processing (Location, Department, Travel Reason, Client Engagement)
        
        Args:
            expense_id: The unique identifier for the expense
            report_id: The report ID containing this expense
            user_id: The SAP Concur user ID
            context_type: The context type (e.g., "TRAVELER")
            
        Returns:
            Complete detailed expense dict, or None if not found
        """
        print(f"Fetching detailed expense data for expense_id: {expense_id}, report_id: {report_id}")
        if not expense_id.strip():
            raise SAPConcurServiceError("Invalid expense ID")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token_from_refresh_token(client)
                response = await client.get(
                    f"{self.settings.sap_concur_api_base_url}/expensereports/v4/users/{user_id}/context/{context_type}/reports/{report_id}/expenses/{expense_id}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                if response.status_code == httpx.codes.NOT_FOUND:
                    return None
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError(
                "Unable to retrieve detailed expense from Concur"
            ) from exc

        try:
            expense = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid Concur expense response"
            ) from exc

        if not isinstance(expense, dict):
            raise SAPConcurServiceError(
                "Invalid Concur expense response"
            )

        return expense


    # Get Token from Concur API
    async def _get_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{self.settings.sap_concur_api_base_url}/oauth2/v0/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            # json={
            #     "client_id": self.settings.sap_concur_client_id,
            #     "client_secret": (
            #         self.settings.sap_concur_client_secret.get_secret_value()
            #     ),
            #     "username": self.settings.sap_concur_username,
            #     "password": self.settings.sap_concur_password.get_secret_value(),
            #     "grant_type" : "refresh_token",
            # },
            payload = f"client_id={self.settings.sap_concur_client_id}&client_secret={self.settings.sap_concur_client_secret.get_secret_value()}&username={self.settings.sap_concur_username}&password={self.settings.sap_concur_password.get_secret_value()}&grant_type=authtoken"
        )
        print(f"Concur Token Response: {response.status_code} - {response.text}")
        response.raise_for_status()

        try:
            token = response.json()["access_token"]
        except (KeyError, TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid SAP Concur authentication response"
            ) from exc

        if not isinstance(token, str) or not token:
            raise SAPConcurServiceError(
                "Invalid SAP Concur authentication response"
            )
        return token


    # Get Token from Concur API
    async def _get_token_from_refresh_token(self, client: httpx.AsyncClient) -> str:

        response = await client.post(
            f"{self.settings.sap_concur_api_base_url}/oauth2/v0/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": self.settings.sap_concur_client_id,
                "client_secret": (
                    self.settings.sap_concur_client_secret.get_secret_value()
                ),
                "grant_type" : "refresh_token",
                "refresh_token": self.settings.sap_concur_refresh_token,
            },
            # data = f"client_id={self.settings.sap_concur_client_id}&client_secret={self.settings.sap_concur_client_secret.get_secret_value()}&grant_type=refresh_token&refresh_token={self.settings.sap_concur_refresh_token}"
        )
        
        response.raise_for_status()
        print("Token status:", response.status_code)

        try:
            payload = response.json()
            token = payload["access_token"]
            new_refresh_token = payload["refresh_token"]
            # print(f"Concur Access Token: {token}")
            # print(f"Concur Refresh Token: {new_refresh_token}")
        except (KeyError, TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid SAP Concur authentication response"
            ) from exc

        if not isinstance(token, str) or not token:
            raise SAPConcurServiceError(
                "Invalid SAP Concur authentication response"
            )
        return token


    # Get yesterday and today's new expense reports from SAP Concur
    async def get_yesterday_and_todays_new_expense_reports_from_sap_concur(
        self,
    ) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await self._get_new_expense_reports(
                    client,
                )
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError("SAP Concur request failed") from exc


    async def _get_new_expense_reports(
        self,
        client: httpx.AsyncClient,
    ) -> list[dict[str, Any]]:
        """
        Fetch Concur expense reports created yesterday or today.
        """
        print("Fetching new expense reports from SAP Concur...")
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)

        token = await self._get_token_from_refresh_token(client)
        print(f"Using token fetch reports from {yesterday} to {tomorrow}")
        url = f"{self.settings.sap_concur_api_base_url}/api/v3.0/expense/reports"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        params = {
            "user": "ALL",
            # "createdDateAfter": yesterday.isoformat(),
            # "createdDateBefore": tomorrow.isoformat(),
            "approvalStatusCode": "A_APPR ",
            # "paymentStatusCode": "P_NOTP",
            "limit": 100,
        }

        response = await client.get(url, headers=headers, params=params)
        # print("Response:", response.status_code, response.text)
        response.raise_for_status()

        try:
            payload = response.json()
            items = payload["Items"]
        except (KeyError, TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid Concur expense reports response"
            ) from exc

        if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items
        ):
            raise SAPConcurServiceError(
                "Invalid Concur expense reports response"
            )

        for item in items:
            create_date = item.get("CreateDate")
            if not isinstance(create_date, str) or not create_date:
                raise SAPConcurServiceError(
                    "Invalid Concur expense reports response"
                )

        return items


    # Get expense reports by email ID from SAP Concur
    async def get_expense_reports_by_email_id_from_sap_concur(
        self,
        email_id: str,
    ) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await self._get_expense_reports_by_email_id(
                    client,
                    email_id,
                )
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError("SAP Concur request failed") from exc


    async def _get_expense_reports_by_email_id(
        self,
        client: httpx.AsyncClient,
        email_id: str,
    ) -> list[dict[str, Any]]:
        """
        Fetch Concur expense reports for a specific user by Email ID.
        """
        print(f"Fetching expense reports for email_id: {email_id}")

        token = await self._get_token_from_refresh_token(client)
        print(f"Using token to fetch reports for user: {email_id}")
        url = f"{self.settings.sap_concur_api_base_url}/api/v3.0/expense/reports"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        params = {
            "user": email_id,
            "limit": 100,
        }

        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()

        try:
            payload = response.json()
            items = payload["Items"]
        except (KeyError, TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid Concur expense reports response"
            ) from exc

        if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items
        ):
            raise SAPConcurServiceError(
                "Invalid Concur expense reports response"
            )

        return items


    async def get_user_id_by_login_id(self, owner_login_id: str) -> str:
        try:
            print(f"Fetching user ID for owner_login_id: {owner_login_id}")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token_from_refresh_token(client)
                url = f"{self.settings.sap_concur_api_base_url}/profile/identity/v4/Users"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                }
                params = {
                    "filter": f'userName eq "{owner_login_id}"',
                }

                response = await client.get(url, headers=headers, params=params)
                print("Response:", response)
                response.raise_for_status()

                try:
                    payload = response.json()
                    user_id = payload["Resources"][0].get("id")
                except (KeyError, TypeError, ValueError, IndexError) as exc:
                    raise SAPConcurServiceError(
                        "Invalid SAP Concur user response"
                    ) from exc
                except ValueError as exc:
                    raise SAPConcurServiceError(
                        "Invalid SAP Concur user response"
                    ) from exc


                return user_id
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError("SAP Concur request failed") from exc


    # Retrieve List items - Custom data (Department, Location, Travel reason, client engagement)
    async def get_list_items_by_id(
        self,
        report_id: str,
        user_id: str,
        context_type: str,
        item_id: str
    ) -> dict[str, Any] | None:
        print(f"========= get_list_items_by_id ========")
        if not report_id.strip():
            raise SAPConcurServiceError("Invalid Concur Expense report ID")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token_from_refresh_token(client)
                response = await client.get(
                    f"{self.settings.sap_concur_api_base_url}/list/v4/items?id={item_id}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                if response.status_code == httpx.codes.NOT_FOUND:
                    return None
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAPConcurServiceError(
                "Unable to reconcile list item in Concur"
            ) from exc

        try:
            items = response.json()
        except (TypeError, ValueError) as exc:
            raise SAPConcurServiceError(
                "Invalid Concur list item response"
            ) from exc

        if not isinstance(items, list):
            raise SAPConcurServiceError(
                "Invalid Concur list item response"
            )

        item = items[0]
        code = item["code"]
        short_code = item["shortCode"]
        value = item["value"]
        if (
            not isinstance(code, str)
            or not isinstance(short_code, str)
            or not isinstance(value, str)
        ):
            raise SAPConcurServiceError(
                "Invalid Concur report response"
            )

        return {
            "code": code,
            "short_code": short_code,
            "value": value
        }