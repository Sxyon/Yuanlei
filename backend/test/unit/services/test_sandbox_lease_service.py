from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.repositories.agent_sandbox_repository import AgentSandboxRepository
from yuxi.services.sandbox_lease_service import SandboxBusyError, SandboxLeaseService
from yuxi.storage.postgres.models_business import AgentSandboxEvent, Base

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

SCOPE_KEY = "agent-project:user-1:coder:project-1"
SANDBOX_ID = "abc123abc123"
NOW = datetime(2026, 9, 18, 12, 0, 0)


@pytest_asyncio.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _add_sandbox(session):
    return await AgentSandboxRepository(session).add(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        scope_key=SCOPE_KEY,
        sandbox_id=SANDBOX_ID,
        lifecycle="persistent",
        resume_policy="auto",
        idle_timeout_seconds=1800,
        now=NOW,
    )


async def _events(session):
    result = await session.execute(
        select(AgentSandboxEvent).order_by(AgentSandboxEvent.created_at.asc(), AgentSandboxEvent.id.asc())
    )
    return list(result.scalars().all())


async def _acquire(session, *, owner_id="run-1", wait_timeout_seconds=0, now=NOW):
    return await SandboxLeaseService(db=session).acquire(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        owner_kind="run",
        owner_id=owner_id,
        ttl_seconds=120,
        wait_timeout_seconds=wait_timeout_seconds,
        now=now,
    )


async def test_acquire_sets_lease_and_records_event(session):
    await _add_sandbox(session)

    row = await _acquire(session)

    assert row.lease_owner_kind == "run"
    assert row.lease_owner_id == "run-1"
    assert row.lease_expires_at == NOW + timedelta(seconds=120)
    events = await _events(session)
    assert [event.kind for event in events] == ["lease_acquired"]


async def test_acquire_same_owner_does_not_duplicate_event(session):
    await _add_sandbox(session)

    await _acquire(session)
    await _acquire(session, now=NOW + timedelta(seconds=10))

    events = await _events(session)
    assert [event.kind for event in events] == ["lease_acquired"]


async def test_acquire_conflict_times_out_with_busy_error(session):
    await _add_sandbox(session)
    await _acquire(session, owner_id="run-2")

    with pytest.raises(SandboxBusyError, match="sandbox_busy"):
        await _acquire(session, owner_id="run-1", now=NOW + timedelta(seconds=1))

    events = await _events(session)
    assert [event.kind for event in events] == ["lease_acquired", "lease_waiting"]
    assert events[1].payload_json["holder_id"] == "run-2"


async def test_acquire_takes_over_expired_lease(session):
    await _add_sandbox(session)
    await _acquire(session, owner_id="run-2")

    row = await _acquire(session, owner_id="run-1", now=NOW + timedelta(seconds=121))

    assert row.lease_owner_id == "run-1"
    events = await _events(session)
    assert [event.kind for event in events] == ["lease_acquired", "lease_acquired"]


async def test_heartbeat_renews_only_for_owner(session):
    await _add_sandbox(session)
    await _acquire(session, owner_id="run-1")
    service = SandboxLeaseService(db=session)

    other = await service.heartbeat(uid="user-1", agent_slug="coder", project_id="project-1", owner_id="run-2", now=NOW)
    renewed = await service.heartbeat(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        owner_id="run-1",
        now=NOW + timedelta(seconds=30),
    )
    row = await AgentSandboxRepository(session).get_for_update(uid="user-1", agent_slug="coder", project_id="project-1")

    assert other is False
    assert renewed is True
    assert row.lease_expires_at == NOW + timedelta(seconds=150)
    assert row.lease_heartbeat_at == NOW + timedelta(seconds=30)


async def test_expired_owner_cannot_heartbeat_or_pass_fencing(session):
    await _add_sandbox(session)
    await _acquire(session, owner_id="run-1")
    service = SandboxLeaseService(db=session)

    renewed = await service.heartbeat(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        owner_id="run-1",
        now=NOW + timedelta(seconds=121),
    )
    active = await service.owns_active(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        owner_id="run-1",
        now=NOW + timedelta(seconds=121),
    )

    assert renewed is False
    assert active is False


async def test_current_owner_passes_fencing(session):
    await _add_sandbox(session)
    await _acquire(session, owner_id="run-1")

    active = await SandboxLeaseService(db=session).owns_active(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        owner_id="run-1",
        now=NOW + timedelta(seconds=30),
    )

    assert active is True


async def test_release_clears_only_owner_lease(session):
    await _add_sandbox(session)
    await _acquire(session, owner_id="run-1")
    service = SandboxLeaseService(db=session)

    stolen = await service.release(uid="user-1", agent_slug="coder", project_id="project-1", owner_id="run-2")
    released = await service.release(uid="user-1", agent_slug="coder", project_id="project-1", owner_id="run-1")
    row = await AgentSandboxRepository(session).get_for_update(uid="user-1", agent_slug="coder", project_id="project-1")

    assert stolen is False
    assert released is True
    assert row.lease_owner_id is None
    assert row.lease_expires_at is None
    events = await _events(session)
    assert [event.kind for event in events] == ["lease_acquired", "lease_released"]


async def test_duplicate_coding_attempt_cannot_reenter_or_release_active_owner(session):
    """同一 turn 的不同 attempt 必须被当作不同 owner 做 fencing。"""
    await _add_sandbox(session)
    service = SandboxLeaseService(db=session)
    first_owner = "coding-turn:abc:first"
    duplicate_owner = "coding-turn:abc:duplicate"
    await service.acquire(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        owner_kind="coding_session",
        owner_id=first_owner,
        wait_timeout_seconds=0,
        now=NOW,
    )

    with pytest.raises(SandboxBusyError):
        await service.acquire(
            uid="user-1",
            agent_slug="coder",
            project_id="project-1",
            owner_kind="coding_session",
            owner_id=duplicate_owner,
            wait_timeout_seconds=0,
            now=NOW,
        )
    assert not await service.release(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        owner_id=duplicate_owner,
        now=NOW,
    )
    assert await service.owns_active(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        owner_id=first_owner,
        now=NOW,
    )


async def test_reconcile_expired_clears_stale_lease_and_records_event(session):
    await _add_sandbox(session)
    await _acquire(session, owner_id="run-1")

    reconciled = await SandboxLeaseService(db=session).reconcile_expired(now=NOW + timedelta(seconds=121))
    row = await AgentSandboxRepository(session).get_for_update(uid="user-1", agent_slug="coder", project_id="project-1")

    assert reconciled == 1
    assert row.lease_owner_id is None
    events = await _events(session)
    assert [event.kind for event in events] == ["lease_acquired", "lease_expired"]
    assert events[1].payload_json == {"owner_kind": "run", "owner_id": "run-1"}


async def test_reconcile_expired_rechecks_locked_row_and_preserves_new_owner():
    """候选扫描后被新 attempt 续租的行，锁后重检必须保留。"""

    class CandidateResult:
        def scalars(self):
            return self

        def all(self):
            return ["sandbox-row-1"]

    renewed = SimpleNamespace(
        id="sandbox-row-1",
        lease_owner_kind="coding_session",
        lease_owner_id="coding-turn:abc:new-attempt",
        lease_expires_at=NOW + timedelta(seconds=120),
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=CandidateResult()),
        scalar=AsyncMock(return_value=renewed),
        flush=AsyncMock(),
    )

    reconciled = await SandboxLeaseService(db=db).reconcile_expired(now=NOW)

    assert reconciled == 0
    assert renewed.lease_owner_id == "coding-turn:abc:new-attempt"
    db.scalar.assert_awaited_once()
