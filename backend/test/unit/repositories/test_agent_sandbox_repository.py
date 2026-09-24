from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.repositories.agent_sandbox_repository import AgentSandboxRepository
from yuxi.storage.postgres.models_business import AgentSandboxEvent, Base

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]


@pytest_asyncio.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def test_repository_adds_and_locks_binding(session):
    repo = AgentSandboxRepository(session)

    row = await repo.add(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        scope_key="agent-project:user-1:coder:project-1",
        sandbox_id="abc123abc123",
        lifecycle="persistent",
        resume_policy="auto",
        idle_timeout_seconds=1800,
    )
    found = await repo.get_for_update(uid="user-1", agent_slug="coder", project_id="project-1")

    assert row.id
    assert row.status == "active"
    assert found is row


async def test_repository_appends_events_in_order(session):
    repo = AgentSandboxRepository(session)

    await repo.append_event(sandbox_id="abc123abc123", kind="created", payload={"generation": "g1"})
    await repo.append_event(sandbox_id="abc123abc123", kind="suspended", payload={"reason": "manual"})

    events = (
        (await session.execute(select(AgentSandboxEvent).order_by(AgentSandboxEvent.created_at.asc())))
        .scalars()
        .all()
    )
    assert [event.kind for event in events] == ["created", "suspended"]
    assert events[1].payload_json == {"reason": "manual"}
