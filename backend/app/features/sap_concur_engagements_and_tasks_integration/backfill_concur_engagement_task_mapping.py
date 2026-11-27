"""Backfill the dedicated Concur engagement and task list into PostgreSQL.

From backend, run:

    python -m app.features.sap_concur_engagements_and_tasks_integration.backfill_concur_engagement_task_mapping

The default is a read-only preview. Add --apply after reviewing the preview.
During cutover, pause sync, manual retry, and list edits until the final preview
reports zero differences. The existing mapping-table migration must be applied.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.features.sap_concur_engagements_and_tasks_integration.models import (
    SAPConcurEngagementTaskMapping,
)


MappingKey = tuple[str, str]
ConcurIds = tuple[str, str | None]
Snapshot = dict[MappingKey, ConcurIds]


class BackfillError(Exception):
    """The backfill could not verify or reconcile the source."""


class ConcurListReader:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.base_url = str(settings.sap_concur_api_base_url).rstrip("/")
        self._access_token: str | None = None

    async def _authenticate(self) -> str:
        try:
            response = await self.client.post(
                f"{self.base_url}/oauth2/v0/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.settings.sap_concur_client_id.get_secret_value(),
                    "client_secret": self.settings.sap_concur_client_secret.get_secret_value(),
                    "refresh_token": self.settings.sap_concur_refresh_token.get_secret_value(),
                },
            )
            response.raise_for_status()
            token = response.json()["access_token"]
        except httpx.HTTPStatusError as exc:
            raise BackfillError(
                f"Concur OAuth returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise BackfillError("Concur OAuth request failed") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise BackfillError("Invalid Concur OAuth response") from exc
        if not isinstance(token, str) or not token.strip():
            raise BackfillError("Invalid Concur OAuth access token")
        return token

    async def get_list_children_page(
        self, list_id: str, page: int, parent_id: str | None
    ) -> httpx.Response:
        url = f"{self.base_url}/list/v4/lists/{list_id}"
        if parent_id is not None:
            url = f"{url}/items/{parent_id}"
        params = {
            "page": page,
            "isDeleted": "false",
            "sortBy": "shortCode",
            "sortDirection": "asc",
        }
        if self._access_token is None:
            self._access_token = await self._authenticate()
        response = await self.client.get(
            f"{url}/children",
            params=params,
            headers={"Authorization": f"Bearer {self._access_token}"},
        )
        if response.status_code == httpx.codes.UNAUTHORIZED:
            self._access_token = await self._authenticate()
            response = await self.client.get(
                f"{url}/children",
                params=params,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
        return response


@dataclass(frozen=True)
class Reconciliation:
    missing: int
    corrections: int
    unchanged: int
    database_only: tuple[MappingKey, ...]


async def _read_children(
    reader: ConcurListReader,
    list_id: str,
    parent_id: str | None = None,
) -> list[dict[str, Any]]:
    context = f"tasks for Concur item {parent_id}" if parent_id else "engagements"
    records: list[dict[str, Any]] = []
    page_number = 1
    expected_paging: tuple[int, int, int] | None = None
    while True:
        try:
            response = await reader.get_list_children_page(
                list_id, page_number, parent_id
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BackfillError(
                f"Concur returned HTTP {exc.response.status_code} reading "
                f"{context}, page {page_number}"
            ) from exc
        except httpx.RequestError as exc:
            raise BackfillError(
                f"Concur request failed reading {context}, page {page_number}"
            ) from exc

        try:
            payload = response.json()
            content = payload["content"]
            meta = payload["page"]
            number, size = meta["number"], meta["size"]
            total, pages = meta["totalElements"], meta["totalPages"]
        except (KeyError, TypeError, ValueError) as exc:
            raise BackfillError(
                f"Invalid Concur response reading {context}, page {page_number}"
            ) from exc

        paging = (size, total, pages)
        if (
            any(type(value) is not int for value in (number, *paging))
            or number != page_number
            or size <= 0
            or total < 0
            or (pages != (total + size - 1) // size and not (total == 0 and pages == 1))
            or (expected_paging is not None and paging != expected_paging)
            or not isinstance(content, list)
            or len(content) != min(size, total - len(records))
            or not all(isinstance(item, dict) for item in content)
        ):
            raise BackfillError(
                f"Inconsistent Concur pagination reading {context}, page {page_number}"
            )
        records.extend(content)
        if page_number >= pages:
            return records
        expected_paging = paging
        page_number += 1


def _item_fields(
    item: dict[str, Any], list_id: str, parent_id: str | None, level: int
) -> tuple[str, str]:
    raw_id = item.get("id")
    code = item.get("shortCode")
    try:
        item_id = str(UUID(raw_id)) if isinstance(raw_id, str) else None
    except ValueError as exc:
        raise BackfillError("Concur returned an invalid item ID") from exc
    if item_id is None or not isinstance(code, str) or not code.strip():
        raise BackfillError("Concur returned an item without an ID or shortCode")

    memberships = item.get("lists")
    if not isinstance(memberships, list):
        raise BackfillError(f"Concur item {item_id} has no list membership")
    matching = [
        member
        for member in memberships
        if isinstance(member, dict) and member.get("id") == list_id
    ]
    if (
        item.get("level") != level
        or item.get("parentId") != parent_id
        or item.get("isDeleted") is not False
        or len(matching) != 1
        or (level == 2 and matching[0].get("hasChildren") is not False)
    ):
        raise BackfillError(
            f"Concur item {item_id} has unexpected list membership or hierarchy"
        )
    return item_id, code.strip()


async def read_concur_snapshot(reader: ConcurListReader, list_id: str) -> Snapshot:
    snapshot: Snapshot = {}
    seen_ids: set[str] = set()
    engagements = await _read_children(reader, list_id)
    for engagement in engagements:
        engagement_id, jobnumber = _item_fields(engagement, list_id, None, 1)
        engagement_key = (jobnumber, "")
        if engagement_key in snapshot or engagement_id in seen_ids:
            raise BackfillError(f"Duplicate Concur engagement {jobnumber!r}")
        snapshot[engagement_key] = (engagement_id, None)
        seen_ids.add(engagement_id)

        tasks = await _read_children(reader, list_id, engagement_id)
        for task in tasks:
            task_id, tasknumber = _item_fields(task, list_id, engagement_id, 2)
            key = (jobnumber, tasknumber)
            if key in snapshot or task_id in seen_ids:
                raise BackfillError(f"Duplicate Concur task mapping {key!r}")
            snapshot[key] = (engagement_id, task_id)
            seen_ids.add(task_id)
    return snapshot


async def _mapping_rows(
    session: AsyncSession,
) -> dict[MappingKey, SAPConcurEngagementTaskMapping]:
    statement = select(SAPConcurEngagementTaskMapping).execution_options(
        populate_existing=True
    )
    rows = await session.scalars(statement)
    return {(row.maconomy_jobnumber, row.maconomy_tasknumber): row for row in rows}


def _concur_ids(row: SAPConcurEngagementTaskMapping) -> tuple[str | None, str | None]:
    return row.sap_concur_engagement_id, row.sap_concur_task_id


async def reconcile_mappings(
    session: AsyncSession, snapshot: Snapshot, *, apply: bool
) -> Reconciliation:
    async with session.begin():
        if apply:
            table_name = SAPConcurEngagementTaskMapping.__tablename__
            await session.execute(
                text(f"LOCK TABLE {table_name} IN SHARE ROW EXCLUSIVE MODE NOWAIT")
            )
        existing = await _mapping_rows(session)
        missing = snapshot.keys() - existing.keys()
        corrections = {
            key
            for key in snapshot.keys() & existing.keys()
            if _concur_ids(existing[key]) != snapshot[key]
        }
        report = Reconciliation(
            missing=len(missing),
            corrections=len(corrections),
            unchanged=len(snapshot) - len(missing) - len(corrections),
            database_only=tuple(sorted(existing.keys() - snapshot.keys())),
        )
        if not apply or report.database_only:
            return report

        for key in missing:
            engagement_id, task_id = snapshot[key]
            session.add(
                SAPConcurEngagementTaskMapping(
                    maconomy_jobnumber=key[0],
                    maconomy_tasknumber=key[1],
                    sap_concur_engagement_id=engagement_id,
                    sap_concur_task_id=task_id,
                )
            )
        for key in corrections:
            row = existing[key]
            row.sap_concur_engagement_id, row.sap_concur_task_id = snapshot[key]

        await session.flush()
        verified_rows = await _mapping_rows(session)
        if {key: _concur_ids(row) for key, row in verified_rows.items()} != snapshot:
            raise BackfillError("Database verification failed; backfill rolled back")
    return report


async def _run(*, apply: bool) -> int:
    settings = get_settings()
    try:
        list_id = str(UUID(settings.sap_engagement_list_id.strip()))
    except ValueError as exc:
        raise BackfillError(
            "SAP_ENGAGEMENT_LIST_ID must be a Concur list UUID"
        ) from exc

    mode = "Apply" if apply else "Read-only preview"
    sys.stdout.write(
        f"{mode}\nConcur list: {list_id}\n"
        f"Database: {settings.postgres_host}:{settings.postgres_port}/"
        f"{settings.postgres_db}\n"
    )
    sys.stdout.flush()
    async with httpx.AsyncClient(timeout=60.0) as client:
        snapshot = await read_concur_snapshot(
            ConcurListReader(client, settings), list_id
        )

    from app.db.session import AsyncSessionFactory, engine

    try:
        async with AsyncSessionFactory() as session:
            report = await reconcile_mappings(session, snapshot, apply=apply)
    finally:
        await engine.dispose()

    sys.stdout.write(
        f"Concur mappings: {len(snapshot)}\n"
        f"Missing rows: {report.missing}\n"
        f"ID corrections: {report.corrections}\n"
        f"Unchanged rows: {report.unchanged}\n"
        f"Database-only rows: {len(report.database_only)}\n"
    )
    if report.database_only:
        for key in report.database_only:
            sys.stdout.write(f"Database-only mapping: {key!r}\n")
        raise BackfillError("Database-only mappings block the backfill")
    if apply:
        sys.stdout.write(
            "Backfill committed and verified against the Concur snapshot.\n"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill engagement and task mappings from SAP Concur."
    )
    parser.add_argument(
        "--apply", action="store_true", help="write and verify the mapping rows"
    )
    args = parser.parse_args()
    try:
        return asyncio.run(_run(apply=args.apply))
    except BackfillError as exc:
        sys.stderr.write(f"Backfill stopped: {exc}\n")
    except ValidationError as exc:
        fields = ", ".join(str(error["loc"][0]) for error in exc.errors())
        sys.stderr.write(f"Backfill stopped: invalid settings for {fields}\n")
    except (SQLAlchemyError, OSError) as exc:
        sys.stderr.write(
            f"Backfill stopped: database operation failed ({type(exc).__name__})\n"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
