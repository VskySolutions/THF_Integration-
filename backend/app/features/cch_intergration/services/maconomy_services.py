import base64
from datetime import datetime
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings

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


    async def get_job_detail_by_job_number(
        self, job_number: str
    ) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)
                instance_id, concurrency_token = await self._start_job_lookup(
                    client, reconnect_token
                )
                return await self._get_job_record(
                    client,
                    reconnect_token,
                    instance_id,
                    concurrency_token,
                    job_number,
                )
        except httpx.HTTPError as exc:
            raise MaconomyServiceError("Maconomy request failed") from exc


    async def get_todays_new_from_maconomy(
            self
        ) -> dict[str, Any] | None:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    reconnect_token = await self._get_reconnect_token(client)
                    return await self._get_new_job_records(
                        client,
                        reconnect_token,
                    )
            except httpx.HTTPError as exc:
                raise MaconomyServiceError("Maconomy request failed") from exc


    async def _get_new_job_records(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
    ) -> dict[str, Any] | None:
        """
        This function will fetch the job number created today in maconomy and  returns the list of jobnumber.
        """
        url = f"{self._jobs_url()}/filter"
        headers = self._container_headers(reconnect_token)
        payload = {
            "restriction": f"template=false and createddate>=date({datetime.now().year},{datetime.now().month},{datetime.now().day})",
            "fields": [ 
                "jobnumber",
                "jobname",
                "name1",
                "customernumber",
                "template",
                "versionnumber"
            ],
            "limit": 2000
        }
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()

        try:
            filter = response.json()["panes"]["filter"]
            records = filter["records"]
            if filter["meta"]["rowCount"] == 0 :
                return []
            job_data = [record["data"] for record in records]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy job response") from exc

        if not isinstance(job_data, list):
            raise MaconomyServiceError("Invalid Maconomy job response")
        return job_data


    async def get_client_detail_by_customer_number(
        self, customer_number: str
    ) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reconnect_token = await self._get_reconnect_token(client)
                instance_id, concurrency_token = await self._start_client_lookup(
                    client, reconnect_token
                )
                return await self._get_client_record(
                    client,
                    reconnect_token,
                    instance_id,
                    concurrency_token,
                    customer_number,
                )
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

    async def _start_job_lookup(
        self, client: httpx.AsyncClient, reconnect_token: str
    ) -> tuple[str, str]:
        url = f"{self._jobs_url()}/instances"
        payload = {
            "panes": {
                "card": {
                    "fields": [
                        "jobnumber",
                        "jobname",
                        "name1",
                        "customernumber",
                        "template",
                        "versionnumber"
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

    async def _get_job_record(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        job_number: str,
    ) -> dict[str, Any] | None:
        job_number = quote(job_number, safe="")
        url = f"{self._jobs_url()}/instances/{instance_id}/data;jobnumber={job_number}"
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token

        response = await client.post(url, headers=headers, json={})
        response.raise_for_status()

        try:
            card = response.json()["panes"]["card"]
            records = card["records"]
            if card["meta"]["rowCount"] != 1 or len(records) != 1:
                return None
            job_data = records[0]["data"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy job response") from exc

        if not isinstance(job_data, dict):
            raise MaconomyServiceError("Invalid Maconomy job response")
        return job_data

    async def _start_client_lookup(
        self, client: httpx.AsyncClient, reconnect_token: str
    ) -> tuple[str, str]:
        url = f"{self._clients_url()}/instances"
        payload = {
            "panes": {
                "card": {
                    "fields": [
                        "customernumber",  # Customer Number
                        "name1",  # Client Name
                        "name2",  # Address
                        "postaldistrict",  # City
                        "zipcode",  # Postal Code
                        "country",  # Country
                        "versionnumber",  # Version Number
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

    async def _get_client_record(
        self,
        client: httpx.AsyncClient,
        reconnect_token: str,
        instance_id: str,
        concurrency_token: str,
        customer_number: str,
    ) -> dict[str, Any] | None:
        customer_number = quote(customer_number, safe="")
        url = (
            f"{self._clients_url()}/instances/{instance_id}/"
            f"data;customernumber={customer_number}"
        )
        headers = self._container_headers(reconnect_token)
        headers["Maconomy-Concurrency-Control"] = concurrency_token

        response = await client.post(url, headers=headers, json={})
        response.raise_for_status()

        try:
            card = response.json()["panes"]["card"]
            records = card["records"]
            if card["meta"]["rowCount"] != 1 or len(records) != 1:
                return None
            client_data = records[0]["data"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy client response") from exc

        if not isinstance(client_data, dict):
            raise MaconomyServiceError("Invalid Maconomy client response")
        return client_data

    def _jobs_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return f"{self.settings.maconomy_url}/maconomy-api/containers/{shortname}/jobs"

    def _clients_url(self) -> str:
        shortname = quote(self.settings.maconomy_shortname, safe="")
        return (
            f"{self.settings.maconomy_url}/maconomy-api/containers/"
            f"{shortname}/customercard"
        )

    @staticmethod
    def _container_headers(reconnect_token: str) -> dict[str, str]:
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }
