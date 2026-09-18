from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.repositories.agent_sandbox_repository import AgentSandboxRepository
from yuxi.services.sandbox_lifecycle_supervisor_service import run_sandbox_lifecycle_tick
from yuxi.storage.postgres.models_business import AgentSandboxEvent, Base, Project

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

WORKDIR = "projects/11111111-1111-4111-8111-111111111111"
SCOPE_KEY = "agent-project:user-1:coder:project-1"
SANDBOX_ID = "abc123abc123"
NOW = datetime(2026, 9, 18, 12, 0, 0)


class _FakeProvider:
    def __init__(self, records=None):
        self.records = list(records or [])
        self.touched: list[str] = []
        self.released: list[str] = []
        self.connections: dict[str, object] = {}

    def list_sandboxes(self):
        return list(self.records)

    def touch(self, sandbox_id: str) -> bool:
        self.touched.append(sandbox_id)
        return sandbox_id in {record.sandbox_id for record in self.records}

    def get_scope(self, scope, **_kwargs):
        return self.connections.get(scope.cache_key)

    def release_scope(self, scope, **_kwargs):
        self.released.append(scope.cache_key)
        self.connections.pop(scope.cache_key, None)


def _record(generation: str) -> SimpleNamespace:
    return SimpleNamespace(sandbox_id=SANDBOX_ID, generation=generation)


@pytest_asyncio.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _add_project(session) -> None:
    session.add(
        Project(
            id="project-1",
            uid="user-1",
            selection_status="implicit",
            workdir_path=WORKDIR,
            directory_mode="managed",
        )
    )
    await session.flush()


async def _add_sandbox(session, *, lifecycle="persistent", idle_timeout_seconds=1800, added_at=None):
    row = await AgentSandboxRepository(session).add(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        scope_key=SCOPE_KEY,
        sandbox_id=SANDBOX_ID,
        lifecycle=lifecycle,
        resume_policy="auto",
        idle_timeout_seconds=idle_timeout_seconds,
        now=added_at or NOW - timedelta(seconds=120),
    )
    await session.flush()
    return row


async def _events(session):
    result = await session.execute(
        select(AgentSandboxEvent).order_by(AgentSandboxEvent.created_at.asc(), AgentSandboxEvent.id.asc())
    )
    return list(result.scalars().all())


async def test_tick_keeps_live_sandbox_alive(session):
    await _add_project(session)
    row = await _add_sandbox(session)
    row.generation = "gen-1"
    await session.flush()
    provider = _FakeProvider([_record("gen-1")])

    counts = await run_sandbox_lifecycle_tick(db=session, provider=provider, now=NOW)

    assert counts["keepalive"] == 1
    assert counts["suspended"] == 0
    assert provider.touched == [SANDBOX_ID]
    assert row.last_keepalive_at == NOW


async def test_tick_suspends_when_container_is_missing(session):
    await _add_project(session)
    row = await _add_sandbox(session)
    row.generation = "gen-1"
    await session.flush()
    provider = _FakeProvider([])

    counts = await run_sandbox_lifecycle_tick(db=session, provider=provider, now=NOW)

    assert counts["suspended"] == 1
    assert row.status == "suspended"
    assert row.suspended_at is not None
    assert provider.released == [SCOPE_KEY]
    events = await _events(session)
    assert [event.kind for event in events] == ["suspended"]
    assert events[0].payload_json == {"reason": "container_missing"}


async def test_tick_suspends_idle_persistent_sandbox(session):
    await _add_project(session)
    row = await _add_sandbox(session)
    row.generation = "gen-1"
    row.last_activity_at = NOW - timedelta(seconds=4000)
    row.last_keepalive_at = NOW
    await session.flush()
    provider = _FakeProvider([_record("gen-1")])

    counts = await run_sandbox_lifecycle_tick(db=session, provider=provider, now=NOW)

    assert counts["suspended"] == 1
    assert counts["keepalive"] == 0
    assert row.status == "suspended"
    events = await _events(session)
    assert events[0].payload_json == {"reason": "idle_suspend"}


async def test_tick_skips_resident_sandbox(session):
    await _add_project(session)
    row = await _add_sandbox(session, lifecycle="resident", idle_timeout_seconds=0)
    row.generation = "gen-1"
    row.last_activity_at = NOW - timedelta(days=7)
    row.last_keepalive_at = NOW - timedelta(days=7)
    await session.flush()
    provider = _FakeProvider([_record("gen-1")])

    counts = await run_sandbox_lifecycle_tick(db=session, provider=provider, now=NOW)

    assert counts == {"checked": 1, "keepalive": 0, "suspended": 0, "generation_changed": 0}
    assert provider.touched == []
    assert row.status == "active"


async def test_tick_records_external_generation_change(session):
    await _add_project(session)
    row = await _add_sandbox(session)
    row.generation = "gen-1"
    row.last_keepalive_at = NOW
    await session.flush()
    provider = _FakeProvider([_record("gen-2")])

    counts = await run_sandbox_lifecycle_tick(db=session, provider=provider, now=NOW)

    assert counts["generation_changed"] == 1
    assert row.generation == "gen-2"
    events = await _events(session)
    assert events[0].kind == "rebuilt"
    assert events[0].payload_json == {"reason": "generation_changed", "generation": "gen-2"}
