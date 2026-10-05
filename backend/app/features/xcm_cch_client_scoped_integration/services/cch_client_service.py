"""Look up and create CCH clients for Maconomy jobs."""

from typing import Any

import httpx

from app.core.config import Settings, get_settings

CLIENT_SEARCH_PATH = "/xcmrestservices/vnext/api/v2/Client/search/advanced"
CLIENT_CREATE_PATH = "/xcmrestservices/vnext/api/v2.1/Client"
TASK_CREATE_PATH = "/xcmrestservices/vnext/api/v2/Task"
AUTH_PATH = "/xcmrestservices/vnext/api/v2/Authenticate/user"
CLIENT_SEARCH_BATCH_SIZE = 20
CLIENT_SEARCH_RESULT_BUFFER = 50


class CCHClientServiceError(Exception):
    """Raised when a CCH client lookup or creation fails."""


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
        matching_numbers: set[str] = set()
        for start in range(0, len(unique_numbers), CLIENT_SEARCH_BATCH_SIZE):
            batch = unique_numbers[start : start + CLIENT_SEARCH_BATCH_SIZE]
            matching_numbers.update(
                await self._search_clients(batch, page_count=len(batch))
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
            response = await self.client.post(
                self._url(CLIENT_SEARCH_PATH),
                headers=self._authorized_headers(),
                json={
                    "pageIndex": 1,
                    "pageCount": page_count + CLIENT_SEARCH_RESULT_BUFFER,
                    "filters": filters,
                },
            )
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

    async def create_clients_and_tasks(
        self, jobs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Independently create each missing CCH client and its task."""
        await self.authenticate()
        processed_jobs: list[dict[str, Any]] = []
        for job in jobs:
            processed_job = dict(job)
            try:
                if job.get("is_exist_in_chh") is not False:
                    raise CCHClientServiceError(
                        "Only jobs absent from CCH can be used to create clients"
                    )
                await self._create_client(job)
            except Exception as exc:
                processed_job["is_created_in_cch"] = False
                processed_job["cchclientcreation"] = {
                    "status": "failed",
                    "error": self._safe_error_message(exc),
                }
                processed_job["cchtaskcreation"] = {
                    "status": "skipped",
                    "taskid": None,
                    "error": "CCH client creation failed",
                }
                processed_jobs.append(processed_job)
                continue

            processed_job["is_created_in_cch"] = True
            processed_job["cchclientcreation"] = {"status": "created"}
            try:
                task_resolution = await self._create_task(job)
                processed_job["cchtaskcreation"] = task_resolution
            except Exception as exc:
                processed_job["cchtaskcreation"] = {
                    "status": "failed",
                    "taskid": None,
                    "error": self._safe_error_message(exc),
                }
            processed_jobs.append(processed_job)
        return processed_jobs

    async def _create_client(self, job: dict[str, Any]) -> None:
        response = await self.client.post(
            self._url(CLIENT_CREATE_PATH),
            headers=self._authorized_headers(),
            json=self._client_payload(job),
        )
        response.raise_for_status()

    async def _create_task(self, job: dict[str, Any]) -> dict[str, Any]:
        task_values = self._task_values(job)
        create_response = await self.client.post(
            self._url(TASK_CREATE_PATH),
            headers=self._authorized_headers(),
            json={
                "accountNumber": task_values["account_number"],
                "taskType": task_values["task_type"],
                "periodEndDate": f'{task_values["period_end_date"]} 00:00:00',
                "taskDescription": task_values["description"]
                #"responsiblePerson": task_values["responsible_person"],
            },
        )
        create_response.raise_for_status()
        try:
            task_id = self._read_task_id(create_response.json())
        except ValueError as exc:
            raise CCHClientServiceError("Invalid CCH task creation response") from exc
        return {"status": "created", "taskid": task_id}

    @staticmethod
    def _task_values(job: dict[str, Any]) -> dict[str, str]:
        task_type = job.get("specification2_description")
        if task_type is None or not str(task_type).strip():
            task_type = "Tax - 1040 Individual"
        required_fields = {
            "account_number": job.get("jobnumber"),
            "task_type": task_type,
            "period_end_date": job.get("periodenddate"),
            "job_number": job.get("jobnumber"),
            "responsible_person": job.get("projectmanager_email"),
            "description": job.get("description"),
        }
        values: dict[str, str] = {}
        for name, value in required_fields.items():
            if value is None or not str(value).strip():
                raise CCHClientServiceError(
                    f"Missing required CCH task value: {name}"
                )
            values[name] = str(value).strip()
        return values

    @staticmethod
    def _read_task_id(task: dict[str, Any]) -> int | str:
        task_id = task.get("taskId")
        if isinstance(task_id, bool) or task_id is None or not str(task_id).strip():
            raise CCHClientServiceError("Invalid CCH task ID")
        if not isinstance(task_id, (int, str)):
            raise CCHClientServiceError("Invalid CCH task ID")
        return task_id

    @staticmethod
    def _client_payload(job: dict[str, Any]) -> dict[str, Any]:
        specification1 = job.get("specification1_description")
        client_type = (
            "Individual"
            if isinstance(specification1, str)
            and specification1.strip().casefold() == "individual"
            else "Entity"
        )
        return {
            "responsiblePerson": "prasad.sawant@vskysolutions.com",#job.get("projectmanager_email"),
            "emailId": (
                job.get("electronicmailaddress")
                if job.get("electronicmailaddress")
                else None
            ),
            # "firstName": to be confirmed
            # "middleName": to be confirmed
            "last_Entity_Name": job.get("name1"),
            # "suffix": to be confirmed
            "clientType": client_type,
            "phoneNumber": job.get("telephone") if job.get("telephone") else None,
            "accountNumber": job.get("jobnumber"),
            "originatingLocationName": "HQ",
            # "originatingLocationId": set by CCH
            "active": "Y",
            # "groupName": to be confirmed
            "primaryTask": (
                job.get("specification2_description")
                if job.get("specification2_description")
                else "Tax - 1040 Individual"
            ),
            "periodEndDate": job.get("periodenddate"),
            # "manager": to be confirmed
            # "auditManager": to be confirmed
            # "auditSenior": to be confirmed
            # "auditPartner": to be confirmed
            "auditStaff": (
                job.get("spec5_email") if job.get("spec5_email") else None
            ),
            "taxPartner": (
                job.get("employee6_email") if job.get("employee6_email") else None
            ),
        }

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

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            return f"CCH/XCM request failed with HTTP {exc.response.status_code}"
        if isinstance(exc, httpx.RequestError):
            return "CCH/XCM request failed or timed out"
        return str(exc)
