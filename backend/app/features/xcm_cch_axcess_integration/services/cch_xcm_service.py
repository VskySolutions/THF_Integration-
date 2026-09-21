from typing import Any

import httpx

from app.core.config import Settings, get_settings


class CCHXCMServiceError(Exception):
    """Raised when a CCH task cannot be searched or created."""


class CCHXCMService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.timeout = 60.0

    async def resolve_tasks(
        self,
        jobs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Search or create a CCH task for each discovered engagement."""
        if not jobs:
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._get_token(client)
                resolved_jobs: list[dict[str, Any]] = []
                for job in jobs:
                    try:
                        resolved_jobs.append(
                            await self._resolve_task(client, token, job)
                        )
                    except Exception as exc:
                        failed_job = dict(job)
                        failed_job["cchtaskresolution"] = {
                            "status": "failed",
                            "taskid": None,
                            "matchcount": None,
                            "error": self._safe_error_message(exc),
                        }
                        resolved_jobs.append(failed_job)
                return resolved_jobs
        except httpx.HTTPError as exc:
            raise CCHXCMServiceError("CCH/XCM request failed") from exc

    async def _resolve_task(
        self,
        client: httpx.AsyncClient,
        token: str,
        job: dict[str, Any],
    ) -> dict[str, Any]:
        search_values = self._prepare_task_values(job)
        search_result = await self._search_tasks(client, token, search_values)
        total_count = search_result["total_count"]
        results = search_result["results"]
        print(f"Total count: {total_count}, Results: {results}")
        resolved_job = dict(job)
        if total_count == 0:
            print("No existing task found, creating a new task...")
            task_id = await self._create_task(client, token, search_values)
            print(f"Created task with ID: {task_id}")
            resolved_job["cchtaskresolution"] = {
                "status": "created",
                "taskid": task_id,
                "matchcount": 0,
            }
            return resolved_job

        if total_count == 1:
            if len(results) != 1:
                raise CCHXCMServiceError("Invalid CCH/XCM task search response")
            task_id = self._read_task_id(results[0])
            resolved_job["cchtaskresolution"] = {
                "status": "existing",
                "taskid": task_id,
                "matchcount": 1,
            }
            return resolved_job

        resolved_job["cchtaskresolution"] = {
            "status": "manual_review",
            "taskid": None,
            "matchcount": total_count,
        }
        return resolved_job

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            self._url("/xcmrestservices/vnext/api/v2/Authenticate/user"),
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

        try:
            token = response.json()["token"]
        except (KeyError, TypeError, ValueError) as exc:
            raise CCHXCMServiceError(
                "Invalid CCH/XCM authentication response"
            ) from exc

        if not isinstance(token, str) or not token.strip():
            raise CCHXCMServiceError("Invalid CCH/XCM authentication response")
        return token.strip()

    async def _search_tasks(
        self,
        client: httpx.AsyncClient,
        token: str,
        search_values: dict[str, str],
    ) -> dict[str, Any]:
        period_end_date = search_values["period_end_date"]
        response = await client.post(
            self._url("/xcmrestservices/vnext/api/v2.1/Task/search"),
            headers=self._authorized_headers(token),
            json={
                "accountNumber": search_values["account_number"],
                "taskType": search_values["task_type"],
                "fromPeriodEndDate": f"{period_end_date} 00:00:00",
                "toPeriodEndDate": f"{period_end_date} 23:59:59",
                "pageCount": 0,
                "pageIndex": 0,
            },
        )
        response.raise_for_status()

        try:
            response_data = response.json()
            total_count = response_data["totalCount"]
            results = response_data["results"]
        except (KeyError, TypeError, ValueError) as exc:
            raise CCHXCMServiceError(
                "Invalid CCH/XCM task search response"
            ) from exc

        if (
            isinstance(total_count, bool)
            or not isinstance(total_count, int)
            or total_count < 0
            or not isinstance(results, list)
            or not all(isinstance(result, dict) for result in results)
        ):
            raise CCHXCMServiceError("Invalid CCH/XCM task search response")

        return {"total_count": total_count, "results": results}

    async def _create_task(
        self,
        client: httpx.AsyncClient,
        token: str,
        task_values: dict[str, str],
    ) -> int | str:
        response = await client.post(
            self._url("/xcmrestservices/vnext/api/v2/Task"),
            headers=self._authorized_headers(token),
            json={
                "accountNumber": task_values["account_number"],
                "taskType": task_values["task_type"],
                "periodEndDate": f'{task_values["period_end_date"]} 00:00:00',
                "taskDescription": f'Task is for Maconomy Engagement Number:{task_values["job_number"]}',
                "responsiblePerson":"prasad.sawant@vskysolutions.com"
            },
        )
        print(response.text)

        response.raise_for_status()
        try:
            response_data = response.json()
        except ValueError as exc:
            raise CCHXCMServiceError(
                "Invalid CCH/XCM task creation response"
            ) from exc
        return self._read_task_id(response_data)

    @staticmethod
    def _prepare_task_values(job: dict[str, Any]) -> dict[str, str]:
        required_fields = {
            "account_number": job.get("customernumber"),
            "task_type": job.get("tasktype"),
            "period_end_date": job.get("periodenddate"),
            "job_number": job.get("jobnumber"),
        }
        prepared_values: dict[str, str] = {}
        for field_name, value in required_fields.items():
            if value is None or not str(value).strip():
                raise CCHXCMServiceError(
                    f"Missing required CCH task value: {field_name}"
                )
            prepared_values[field_name] = str(value).strip()
        return prepared_values

    @staticmethod
    def _read_task_id(task: dict[str, Any]) -> int | str:
        task_id = task.get("taskId")
        if isinstance(task_id, bool) or task_id is None or not str(task_id).strip():
            raise CCHXCMServiceError("Invalid CCH/XCM task ID")
        if not isinstance(task_id, (int, str)):
            raise CCHXCMServiceError("Invalid CCH/XCM task ID")
        return task_id

    def _authorized_headers(self, token: str) -> dict[str, str]:
        return {
            "APIKey": self.settings.cch_axcess_api_key.get_secret_value(),
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{str(self.settings.cch_axcess_url).rstrip('/')}{path}"

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            return f"CCH/XCM request failed with HTTP {exc.response.status_code}"
        if isinstance(exc, httpx.RequestError):
            return "CCH/XCM request failed or timed out"
        return str(exc)
