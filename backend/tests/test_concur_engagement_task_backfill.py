import asyncio
from contextlib import asynccontextmanager
from os import environ
from urllib.parse import parse_qs
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import AnyHttpUrl, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings
from app.features.sap_concur_engagements_and_tasks_integration.models import (
    SAPConcurEngagementTaskIntegrationLog,
    SAPConcurEngagementTaskMapping,
)
from app.features.sap_concur_engagements_and_tasks_integration.models.integration_log import (
    EngagementTaskIntegrationAction,
    EngagementTaskIntegrationStatus,
)
from app.features.sap_concur_engagements_and_tasks_integration.backfill_concur_engagement_task_mapping import (
    BackfillError,
    ConcurListReader,
    Reconciliation,
    read_concur_snapshot,
    reconcile_mappings,
)


LIST_ID, E1, E2, E3, T1, T2, T3 = (str(UUID(int=n)) for n in range(1, 8))
ROOT = f"/list/v4/lists/{LIST_ID}/children"


def _children(parent_id):
    return f"/list/v4/lists/{LIST_ID}/items/{parent_id}/children"


def _item(item_id, code, parent=None, *, has_children=False):
    return {
        "id": item_id,
        "shortCode": code,
        "parentId": parent,
        "level": 1 if parent is None else 2,
        "isDeleted": False,
        "lists": [{"id": LIST_ID, "hasChildren": has_children}],
    }


def _page(items, *, number=1, size=100, total=None):
    total = len(items) if total is None else total
    return {
        "content": items,
        "page": {
            "number": number,
            "size": size,
            "totalElements": total,
            "totalPages": (total + size - 1) // size,
        },
    }


def _snapshot(pages, *, reject_first_token=False):
    calls = []
    token_calls = 0

    def handle(request):
        nonlocal token_calls
        if request.method == "POST":
            assert request.url.path == "/oauth2/v0/token"
            assert parse_qs(request.content.decode()) == {
                "grant_type": ["refresh_token"],
                "client_id": ["client"],
                "client_secret": ["secret"],
                "refresh_token": ["refresh"],
            }
            token_calls += 1
            return httpx.Response(200, json={"access_token": f"token-{token_calls}"})

        assert request.method == "GET"
        assert request.headers["Authorization"] == f"Bearer token-{token_calls}"
        assert request.url.params["isDeleted"] == "false"
        assert request.url.params["sortBy"] == "shortCode"
        assert request.url.params["sortDirection"] == "asc"
        if reject_first_token and token_calls == 1:
            return httpx.Response(401)
        key = (request.url.path, int(request.url.params["page"]))
        calls.append(key)
        payload = pages[key]
        return (
            payload
            if isinstance(payload, httpx.Response)
            else httpx.Response(200, json=payload)
        )

    async def run():
        settings = Settings.model_construct(
            sap_concur_api_base_url=AnyHttpUrl("https://concur.example"),
            sap_concur_client_id=SecretStr("client"),
            sap_concur_client_secret=SecretStr("secret"),
            sap_concur_refresh_token=SecretStr("refresh"),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await read_concur_snapshot(
                ConcurListReader(client, settings), LIST_ID
            )

    return asyncio.run(run()), calls, token_calls


def test_reads_all_pages_and_keys_repeated_task_codes_by_parent():
    pages = {
        (ROOT, 1): _page([_item(E1, "0001", has_children=True)], size=1, total=3),
        (ROOT, 2): _page(
            [_item(E2, "E002", has_children=True)], number=2, size=1, total=3
        ),
        (ROOT, 3): _page([_item(E3, "E003")], number=3, size=1, total=3),
        (_children(E1), 1): _page([_item(T1, "t007", E1)], size=1, total=2),
        (_children(E1), 2): _page([_item(T2, "t008", E1)], number=2, size=1, total=2),
        (_children(E2), 1): _page([_item(T3, "t007", E2)]),
        (_children(E3), 1): _page([]),
    }

    snapshot, calls, token_calls = _snapshot(pages, reject_first_token=True)

    assert snapshot == {
        ("0001", ""): (E1, None),
        ("E002", ""): (E2, None),
        ("E003", ""): (E3, None),
        ("0001", "t007"): (E1, T1),
        ("0001", "t008"): (E1, T2),
        ("E002", "t007"): (E2, T3),
    }
    assert calls == list(pages)
    assert token_calls == 2


@pytest.mark.parametrize(
    ("second_page", "error"),
    [
        ({"content": []}, "Invalid Concur response"),
        (_page([], number=2, size=1, total=2), "Inconsistent Concur pagination"),
        (_page([_item(E2, "E002")], size=1, total=2), "Inconsistent Concur pagination"),
        (httpx.Response(503, text="private body"), "HTTP 503"),
    ],
)
def test_incomplete_source_stops_before_returning_a_snapshot(second_page, error):
    with pytest.raises(BackfillError, match=error) as excinfo:
        _snapshot(
            {
                (ROOT, 1): _page([_item(E1, "E001")], size=1, total=2),
                (ROOT, 2): second_page,
            }
        )
    assert "private body" not in str(excinfo.value)


@pytest.mark.parametrize(
    ("tasks", "error"),
    [
        ([_item(T1, "   ", E1)], "without an ID or shortCode"),
        ([_item(T1, "T1", E2)], "unexpected list membership or hierarchy"),
        (
            [_item(T1, "T1", E1, has_children=True)],
            "unexpected list membership or hierarchy",
        ),
        ([_item(T1, "T1", E1), _item(T2, "T1", E1)], "Duplicate Concur task mapping"),
    ],
)
def test_rejects_ambiguous_or_invalid_task_mappings(tasks, error):
    with pytest.raises(BackfillError, match=error):
        _snapshot(
            {
                (ROOT, 1): _page([_item(E1, "E001", has_children=True)]),
                (_children(E1), 1): _page(tasks),
            }
        )


@asynccontextmanager
async def _postgres_sessions(database_url):
    schema = f"backfill_test_{uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    async with admin_engine.begin() as connection:
        await connection.execute(CreateSchema(schema))
    engine = create_async_engine(
        database_url, connect_args={"server_settings": {"search_path": schema}}
    )
    mapping = SAPConcurEngagementTaskMapping.__table__
    log = SAPConcurEngagementTaskIntegrationLog.__table__
    try:
        async with engine.begin() as connection:
            await connection.run_sync(mapping.create)
            await connection.run_sync(log.create)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await admin_engine.dispose()


@pytest.fixture
def postgres_url():
    url = environ.get("CONCUR_BACKFILL_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "set CONCUR_BACKFILL_TEST_DATABASE_URL to a disposable PostgreSQL database"
        )
    return url


def test_preview_apply_and_rerun_preserve_history(postgres_url):
    async def run():
        async with _postgres_sessions(postgres_url) as sessions:
            async with sessions.begin() as session:
                row = SAPConcurEngagementTaskMapping(
                    maconomy_jobnumber="E001",
                    maconomy_tasknumber="",
                )
                session.add(row)
                await session.flush()
                row_id = row.id
                session.add(
                    SAPConcurEngagementTaskIntegrationLog(
                        sap_concur_engagement_task_mapping_id=row_id,
                        maconomy_jobnumber="E001",
                        maconomy_tasknumber="",
                        instance="test",
                        base_url="https://maconomy.example",
                        username="test",
                        action=EngagementTaskIntegrationAction.CREATE,
                        status=EngagementTaskIntegrationStatus.SUCCESS,
                    )
                )

            snapshot = {("E001", ""): (E1, None), ("E001", "T1"): (E1, T1)}
            async with sessions() as session:
                assert await reconcile_mappings(
                    session, snapshot, apply=False
                ) == Reconciliation(
                    missing=1,
                    corrections=1,
                    unchanged=0,
                    database_only=(),
                )
                assert (
                    await session.scalar(
                        select(SAPConcurEngagementTaskMapping.sap_concur_engagement_id)
                    )
                    is None
                )
            async with sessions() as session:
                await reconcile_mappings(session, snapshot, apply=True)
                assert await reconcile_mappings(
                    session, snapshot, apply=True
                ) == Reconciliation(
                    missing=0,
                    corrections=0,
                    unchanged=2,
                    database_only=(),
                )
                assert (
                    await session.scalar(
                        select(
                            SAPConcurEngagementTaskIntegrationLog.sap_concur_engagement_task_mapping_id
                        )
                    )
                    == row_id
                )
                assert (
                    await session.get(SAPConcurEngagementTaskMapping, row_id)
                ).sap_concur_engagement_id == E1

    asyncio.run(run())


def test_database_only_mapping_blocks_all_writes(postgres_url):
    async def run():
        async with _postgres_sessions(postgres_url) as sessions:
            async with sessions.begin() as session:
                session.add(
                    SAPConcurEngagementTaskMapping(
                        maconomy_jobnumber="db-only",
                        maconomy_tasknumber="",
                    )
                )
            async with sessions() as session:
                report = await reconcile_mappings(
                    session, {("E001", ""): (E1, None)}, apply=True
                )
                assert report.database_only == (("db-only", ""),)
                assert (
                    await session.scalars(
                        select(SAPConcurEngagementTaskMapping.maconomy_jobnumber)
                    )
                ).all() == ["db-only"]

    asyncio.run(run())


def test_failed_verification_rolls_back_flushed_writes(postgres_url, monkeypatch):
    from app.features.sap_concur_engagements_and_tasks_integration import (
        backfill_concur_engagement_task_mapping as backfill,
    )

    actual_read = backfill._mapping_rows
    reads = 0

    async def fail_verification(session):
        nonlocal reads
        rows = await actual_read(session)
        reads += 1
        if reads == 2:
            assert rows[("E001", "")].sap_concur_engagement_id == E1
            return {}
        return rows

    monkeypatch.setattr(backfill, "_mapping_rows", fail_verification)

    async def run():
        async with _postgres_sessions(postgres_url) as sessions, sessions() as session:
            with pytest.raises(BackfillError, match="verification failed"):
                await reconcile_mappings(
                    session, {("E001", ""): (E1, None)}, apply=True
                )
            assert (
                await session.scalars(select(SAPConcurEngagementTaskMapping))
            ).all() == []

    asyncio.run(run())
