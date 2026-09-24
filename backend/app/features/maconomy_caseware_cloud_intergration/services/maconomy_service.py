import asyncio
import base64
import json
from datetime import date, datetime, timedelta
from time import monotonic
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from app.core.config import Settings

AUTH_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.authentication+json; charset=utf-8; version=3.0"
)
CONTAINER_ACCEPT = (
    "application/vnd.deltek.maconomy.containers+json; charset=utf-8; version=9.0"
)
CONTAINER_CONTENT_TYPE = (
    "application/vnd.deltek.maconomy.containers+json; charset=UTF-8; version=9.0"
)
JOB_FIELDS = [
    "jobnumber",
    "jobname",
    "name1",
    "name2",
    "name3",
    "name4",
    "description1",
    "postaldistrict",
    "country",
    "customernumber",
    "template",
    "closed",
    "versionnumber",
    "createddate",
    "changeddate",
    "text19",
    "telephone",
    "workcompleteddate",
    "startingdate",
    "zipcode",
    "electronicmailaddress",
]


class MaconomyServiceError(Exception):
    pass


class MaconomyService:
    _cached_reconnect_token: str | None = None
    _token_expires_at: float = 0.0
    _token_cache_key: tuple[str, str, str] | None = None
    _token_lock = asyncio.Lock()

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        shortname = quote(settings.maconomy_shortname, safe="")
        self.jobs_url = f"{settings.maconomy_url}/maconomy-api/containers/{shortname}/jobs"
        self.countries_url = (
            f"{settings.maconomy_url}/maconomy-api/containers/{shortname}/countries"
        )

    async def _headers(self) -> dict[str, str]:
        reconnect_token = await self._get_reconnect_token()
        return {
            "Accept": CONTAINER_ACCEPT,
            "Content-Type": CONTAINER_CONTENT_TYPE,
            "Authorization": f"X-Reconnect {reconnect_token}",
        }

    async def _get_reconnect_token(self) -> str:
        cache_key = (
            self.settings.maconomy_url,
            self.settings.maconomy_shortname,
            self.settings.maconomy_username,
        )
        if (
            self.__class__._cached_reconnect_token
            and self.__class__._token_cache_key == cache_key
            and monotonic() < self.__class__._token_expires_at
        ):
            return self.__class__._cached_reconnect_token

        async with self.__class__._token_lock:
            if (
                self.__class__._cached_reconnect_token
                and self.__class__._token_cache_key == cache_key
                and monotonic() < self.__class__._token_expires_at
            ):
                return self.__class__._cached_reconnect_token

            credentials = (
                f"{self.settings.maconomy_username}:"
                f"{self.settings.maconomy_password.get_secret_value()}"
            )
            encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
            shortname = quote(self.settings.maconomy_shortname, safe="")
            try:
                response = await self.client.get(
                    f"{self.settings.maconomy_url}/maconomy-api/auth/{shortname}/login",
                    headers={
                        "Accept": AUTH_CONTENT_TYPE,
                        "Maconomy-Authentication": "X-Reconnect",
                        "Authorization": f"Basic {encoded}",
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise MaconomyServiceError(
                    f"Maconomy authentication failed (HTTP {exc.response.status_code})"
                ) from exc
            except httpx.HTTPError as exc:
                raise MaconomyServiceError("Maconomy authentication request failed") from exc
            token = response.headers.get("Maconomy-Reconnect", "").strip()
            if response.status_code != 204 or not token:
                raise MaconomyServiceError("Invalid Maconomy authentication response")
            self.__class__._cached_reconnect_token = token
            self.__class__._token_cache_key = cache_key
            self.__class__._token_expires_at = monotonic() + (29 * 60)
            return token

    @classmethod
    def _clear_cached_token(cls) -> None:
        cls._cached_reconnect_token = None
        cls._token_expires_at = 0.0
        cls._token_cache_key = None

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        concurrency_token: str | None = None,
    ) -> httpx.Response:
        return await self._post_container(
            self.jobs_url,
            path,
            payload,
            concurrency_token=concurrency_token,
            resource_name="job",
        )

    async def _post_container(
        self,
        container_url: str,
        path: str,
        payload: dict[str, Any],
        *,
        concurrency_token: str | None = None,
        resource_name: str,
    ) -> httpx.Response:
        headers = await self._headers()
        if concurrency_token is not None:
            headers["Maconomy-Concurrency-Control"] = concurrency_token
        try:
            response = await self.client.post(
                f"{container_url}{path}", headers=headers, json=payload
            )
            if response.status_code in (401, 403):
                self._clear_cached_token()
                headers = await self._headers()
                if concurrency_token is not None:
                    headers["Maconomy-Concurrency-Control"] = concurrency_token
                response = await self.client.post(
                    f"{container_url}{path}",
                    headers=headers,
                    json=payload,
                )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MaconomyServiceError(
                f"Maconomy {resource_name} request failed "
                f"(HTTP {exc.response.status_code})"
            ) from exc
        except httpx.HTTPError as exc:
            raise MaconomyServiceError(
                f"Maconomy {resource_name} request failed or timed out"
            ) from exc
        return response

    @staticmethod
    def _records(response: httpx.Response, pane: str) -> list[dict[str, Any]]:
        try:
            data = response.json()["panes"][pane]
            if data["meta"]["rowCount"] == 0:
                return []
            records = data["records"]
            if not isinstance(records, list):
                raise ValueError("Records must be a list")
            result = [record["data"] for record in records]
            if any(not isinstance(record, dict) for record in result):
                raise ValueError("Record data must be an object")
            return result
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(f"Invalid Maconomy {pane} response") from exc

    async def get_recent_jobs(self) -> list[dict[str, Any]]:
        today = date.today()
        yesterday = today - timedelta(days=1)
        start = f"date({yesterday.year},{yesterday.month},{yesterday.day})"
        end = f"date({today.year},{today.month},{today.day})"
        response = await self._post(
            "/filter",
            {
                "restriction": (
                    "template=false and closed=false and "
                    f"((createddate>={start} and createddate<={end}) or "
                    f"(changeddate>={start} and changeddate<={end}))"
                ),
                "fields": JOB_FIELDS,
                "limit": 2000,
            },
        )
        records = self._records(response, "filter")
        candidates: list[dict[str, Any]] = []
        for record in records:
            candidate = self._parse_text19(record)
            candidate["versionnumber"] = self._parse_version(
                candidate.get("versionnumber")
            )
            candidate["syncAction"] = (
                "TOCREATE" if candidate["text19"] is None else "TOUPDATE"
            )
            if candidate["syncAction"] == "TOUPDATE":
                current_version = self._parse_version(candidate.get("versionnumber"))
                if current_version <= candidate["text19"]["syncedVersion"]:
                    continue
            candidates.append(candidate)
        return candidates

    async def get_country_codes(self) -> dict[str, str]:
        """Return Maconomy country names mapped to their two-letter ISO codes."""
        response = await self._post_container(
            self.countries_url,
            "/filter",
            {
                "restriction": "",
                "fields": ["isocode", "name"],
                "limit": 1000,
                "offset": 0,
            },
            resource_name="country list",
        )
        records = self._records(response, "filter")
        country_codes: dict[str, str] = {}
        for record in records:
            name = record.get("name")
            iso_code = record.get("isocode")
            if not isinstance(name, str) or not name.strip():
                continue
            if (
                not isinstance(iso_code, str)
                or len(iso_code.strip()) != 2
                or not iso_code.strip().isalpha()
            ):
                continue
            normalized_name = name.strip().casefold()
            normalized_iso_code = iso_code.strip().upper()
            existing_code = country_codes.get(normalized_name)
            if existing_code is not None and existing_code != normalized_iso_code:
                raise MaconomyServiceError(
                    f"Maconomy country {name!r} has multiple ISO codes"
                )
            country_codes[normalized_name] = normalized_iso_code
        if not country_codes:
            raise MaconomyServiceError(
                "Maconomy country list did not contain any valid ISO mappings"
            )
        return country_codes

    async def get_job_by_number(self, job_number: str) -> dict[str, Any] | None:
        if not isinstance(job_number, str) or not job_number.strip():
            raise MaconomyServiceError("Maconomy jobnumber is required")
        try:
            record, _, _ = await self._bind_job(job_number, fields=JOB_FIELDS)
        except MaconomyServiceError as exc:
            if str(exc) == f"Maconomy job {job_number} was not found":
                return None
            raise
        candidate = self._parse_text19(record)
        candidate["versionnumber"] = self._parse_version(candidate.get("versionnumber"))
        candidate["syncAction"] = (
            "TOCREATE" if candidate["text19"] is None else "TOUPDATE"
        )
        if (
            candidate["syncAction"] == "TOUPDATE"
            and candidate["versionnumber"] <= candidate["text19"]["syncedVersion"]
        ):
            candidate["syncAction"] = "ALREADY_SYNCED"
        return candidate

    async def update_job_text19(
        self,
        *,
        job_number: str,
        source_version: int,
        checkpoint: dict[str, Any],
        expected_text19: dict[str, Any] | None = None,
    ) -> int:
        job, instance_id, concurrency_token = await self._bind_job(job_number)
        current_version = self._parse_version(job.get("versionnumber"))
        if current_version != source_version:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} changed before text19 could be saved"
            )
        current_text19 = job.get("text19")
        if expected_text19 is None:
            if current_text19 is not None and (
                not isinstance(current_text19, str) or current_text19.strip()
            ):
                raise MaconomyServiceError(
                    f"Maconomy job {job_number} already has a text19 mapping"
                )
        else:
            if not isinstance(current_text19, str):
                raise MaconomyServiceError(
                    f"Maconomy job {job_number} text19 changed before update"
                )
            try:
                current_checkpoint = json.loads(current_text19)
            except json.JSONDecodeError as exc:
                raise MaconomyServiceError(
                    f"Maconomy job {job_number} text19 changed before update"
                ) from exc
            if current_checkpoint != expected_text19:
                raise MaconomyServiceError(
                    f"Maconomy job {job_number} text19 changed before update"
                )

        serialized_checkpoint = json.dumps(
            checkpoint,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        await self._post(
            f"/instances/{instance_id}/data/panes/card/0",
            {"data": {"text19": serialized_checkpoint}},
            concurrency_token,
        )

        saved_job, _, _ = await self._bind_job(job_number)
        saved_version = self._parse_version(saved_job.get("versionnumber"))
        if saved_version != source_version + 1:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} version did not increase by one"
            )
        try:
            saved_checkpoint = json.loads(saved_job.get("text19"))
        except (TypeError, json.JSONDecodeError) as exc:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} text19 write could not be verified"
            ) from exc
        if saved_checkpoint != checkpoint:
            raise MaconomyServiceError(
                f"Maconomy job {job_number} text19 write could not be verified"
            )
        return saved_version

    async def _bind_job(
        self,
        job_number: str,
        fields: list[str] | None = None,
    ) -> tuple[dict[str, Any], str, str]:
        instance_response = await self._post(
            "/instances",
            {
                "panes": {
                    "card": {
                        "fields": fields or ["jobnumber", "versionnumber", "text19"]
                    }
                }
            },
        )
        try:
            instance_data = instance_response.json()
            instance_id_value = instance_data["meta"]["containerInstanceId"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MaconomyServiceError("Invalid Maconomy instance response") from exc
        instance_id = self._response_uuid(instance_id_value, "containerInstanceId")
        concurrency_token = self._response_uuid(
            instance_response.headers.get("Maconomy-Concurrency-Control"),
            "Maconomy-Concurrency-Control",
        )

        bind_response = await self._post(
            f"/instances/{instance_id}/data;jobnumber={quote(job_number, safe='')}",
            {},
            concurrency_token,
        )
        bound_token = self._response_uuid(
            bind_response.headers.get("Maconomy-Concurrency-Control"),
            "Maconomy-Concurrency-Control",
        )
        records = self._records(bind_response, "card")
        if len(records) != 1 or str(records[0].get("jobnumber")) != job_number:
            raise MaconomyServiceError(f"Maconomy job {job_number} was not found")
        return records[0], instance_id, bound_token

    @staticmethod
    def _response_uuid(value: Any, field_name: str) -> str:
        try:
            return str(UUID(value))
        except (AttributeError, TypeError, ValueError) as exc:
            raise MaconomyServiceError(
                f"Invalid Maconomy {field_name} response"
            ) from exc

    @staticmethod
    def _parse_version(value: Any) -> int:
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MaconomyServiceError("Invalid Maconomy versionnumber")
        return value

    @staticmethod
    def _parse_text19(record: dict[str, Any]) -> dict[str, Any]:
        parsed_record = dict(record)
        text19 = record.get("text19")

        if text19 is None or (isinstance(text19, str) and not text19.strip()):
            parsed_record["text19"] = None
            return parsed_record

        if not isinstance(text19, str):
            parsed_record["text19"] = None
            return parsed_record

        try:
            parsed_text19 = json.loads(text19)
        except json.JSONDecodeError:
            parsed_record["text19"] = None
            return parsed_record

        if not MaconomyService._is_valid_text19(parsed_text19):
            parsed_record["text19"] = None
            return parsed_record

        if parsed_text19["addressNo"] == "":
            parsed_text19["addressNo"] = None

        parsed_record["text19"] = parsed_text19
        return parsed_record

    @staticmethod
    def _is_valid_text19(value: Any) -> bool:
        if not isinstance(value, dict):
            return False

        required_fields = {
            "entityId",
            "entityNo",
            "syncedVersion",
            "addressId",
            "addressNo",
            "lastUpdateOnUTC",
        }
        if not required_fields.issubset(value):
            return False

        try:
            UUID(value["entityId"])
        except (AttributeError, TypeError, ValueError):
            return False

        address_id = value["addressId"]
        if address_id is not None:
            try:
                UUID(address_id)
            except (AttributeError, TypeError, ValueError):
                return False

        if not isinstance(value["entityNo"], str) or not value["entityNo"].strip():
            return False

        synced_version = value["syncedVersion"]
        if (
            isinstance(synced_version, bool)
            or not isinstance(synced_version, int)
            or synced_version < 0
        ):
            return False

        address_no = value["addressNo"]
        if isinstance(address_no, bool) or (
            address_no is not None and not isinstance(address_no, (str, int))
        ):
            return False

        timestamp = value["lastUpdateOnUTC"]
        if not isinstance(timestamp, str):
            return False
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed_timestamp.utcoffset() == timedelta(0)
