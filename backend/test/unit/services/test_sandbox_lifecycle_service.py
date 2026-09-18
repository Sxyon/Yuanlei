from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.agents.backends.sandbox.policy import SandboxPolicy
from yuxi.repositories.agent_sandbox_repository import AgentSandboxRepository
from yuxi.services.sandbox_lifecycle_service import (
    SandboxLifecycleService,
    SandboxRebuildConfirmationRequired,
    resolve_agent_sandbox_policy,
    resolve_dispatch_runtime_scope,
    runtime_scope_for_policy,
)
from yuxi.storage.postgres.models_business import (
    Agent,
    AgentSandbox,
    AgentSandboxEvent,
    Base,
    ProjectAgent,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

WORKDIR = "projects/11111111-1111-4111-8111-111111111111"


class _FakeProvider:
    def __init__(self):
        self.connections: dict[str, object] = {}
        self.create_calls: list[dict] = []
        self.release_calls: list[str] = []

    def get_scope(
        self,
        scope,
        *,
        create_if_missing: bool = False,
        inherit_env: bool = True,
        workdir_path: str | None = None,
        lifecycle: str | None = None,
        idle_timeout_seconds: int | None = None,
    ):
        if scope.cache_key in self.connections:
            return self.connections[scope.cache_key]
        if not create_if_missing:
            return None
        self.create_calls.append(
            {
                "scope": scope,
                "lifecycle": lifecycle,
                "idle_timeout_seconds": idle_timeout_seconds,
                "workdir_path": workdir_path,
            }
        )
        connection = SimpleNamespace(
            cache_key=scope.cache_key,
            sandbox_id=scope.sandbox_id,
            generation=f"gen-{len(self.create_calls)}",
            workdir_path=workdir_path,
        )
        self.connections[scope.cache_key] = connection
        return connection

    def release_scope(self, scope, **_kwargs):
        self.release_calls.append(scope.cache_key)
        self.connections.pop(scope.cache_key, None)


@pytest_asyncio.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


def _dedicated_policy(**overrides) -> SandboxPolicy:
    values = {
        "mode": "dedicated",
        "lifecycle": "persistent",
        "resume_policy": "auto",
        "idle_suspend_seconds": 1800,
    }
    values.update(overrides)
    return SandboxPolicy(**values)


async def _get_row(session, *, uid="user-1", agent_slug="coder", project_id="project-1") -> AgentSandbox:
    row = await AgentSandboxRepository(session).get_for_update(
        uid=uid, agent_slug=agent_slug, project_id=project_id
    )
    assert row is not None
    return row


async def test_ensure_ready_creates_row_and_forwards_policy(session):
    provider = _FakeProvider()
    service = SandboxLifecycleService(session, provider=provider)

    connection = await service.ensure_ready(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        policy=_dedicated_policy(),
        workdir_path=WORKDIR,
    )

    row = await _get_row(session)
    assert connection.generation == "gen-1"
    assert row.status == "active"
    assert row.generation == "gen-1"
    assert row.lifecycle == "persistent"
    assert row.resume_policy == "auto"
    assert row.idle_timeout_seconds == 1800
    assert provider.create_calls[0]["lifecycle"] == "persistent"
    assert provider.create_calls[0]["idle_timeout_seconds"] == 1800
    events = (await session.execute(select(AgentSandboxEvent))).scalars().all()
    assert [event.kind for event in events] == ["created"]


async def test_ensure_ready_reuses_live_container_without_rebuild(session):
    provider = _FakeProvider()
    service = SandboxLifecycleService(session, provider=provider)
    kwargs = dict(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        policy=_dedicated_policy(),
        workdir_path=WORKDIR,
    )

    first = await service.ensure_ready(**kwargs)
    second = await service.ensure_ready(**kwargs)

    assert first is second
    assert len(provider.create_calls) == 1


async def test_ensure_ready_suspends_then_rebuilds_when_container_missing(session):
    provider = _FakeProvider()
    service = SandboxLifecycleService(session, provider=provider)
    kwargs = dict(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        policy=_dedicated_policy(),
        workdir_path=WORKDIR,
    )
    await service.ensure_ready(**kwargs)
    provider.connections.clear()

    connection = await service.ensure_ready(**kwargs)

    row = await _get_row(session)
    assert connection.generation == "gen-2"
    assert row.status == "active"
    assert row.generation == "gen-2"
    kinds = [event.kind for event in (await session.execute(select(AgentSandboxEvent))).scalars().all()]
    assert kinds == ["created", "suspended", "rebuilt"]
    events = (await session.execute(select(AgentSandboxEvent).order_by(AgentSandboxEvent.created_at.asc()))).scalars().all()
    assert events[1].payload_json == {"reason": "container_missing"}


async def test_ensure_ready_requires_confirmation_before_rebuild(session):
    provider = _FakeProvider()
    service = SandboxLifecycleService(session, provider=provider)
    await service.ensure_ready(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        policy=_dedicated_policy(),
        workdir_path=WORKDIR,
    )
    await service.suspend(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        workdir_path=WORKDIR,
        reason="idle_suspend",
        actor_kind="supervisor",
    )
    create_count = len(provider.create_calls)

    with pytest.raises(SandboxRebuildConfirmationRequired):
        await service.ensure_ready(
            uid="user-1",
            agent_slug="coder",
            project_id="project-1",
            policy=_dedicated_policy(resume_policy="confirm"),
            workdir_path=WORKDIR,
        )

    assert len(provider.create_calls) == create_count
    row = await _get_row(session)
    assert row.status == "suspended"


async def test_ensure_ready_rebuilds_on_credential_change(session):
    provider = _FakeProvider()
    service = SandboxLifecycleService(session, provider=provider)
    await service.ensure_ready(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        policy=_dedicated_policy(),
        workdir_path=WORKDIR,
        credential_fingerprint="fp-1",
    )

    connection = await service.ensure_ready(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        policy=_dedicated_policy(),
        workdir_path=WORKDIR,
        credential_fingerprint="fp-2",
    )

    row = await _get_row(session)
    assert connection.generation == "gen-2"
    assert row.credential_fingerprint == "fp-2"
    assert provider.release_calls == ["agent-project:user-1:coder:project-1"]
    events = (await session.execute(select(AgentSandboxEvent).order_by(AgentSandboxEvent.created_at.asc()))).scalars().all()
    assert [event.kind for event in events] == ["created", "suspended", "rebuilt"]
    assert events[1].payload_json == {"reason": "credential_changed"}


async def test_suspend_is_idempotent(session):
    provider = _FakeProvider()
    service = SandboxLifecycleService(session, provider=provider)
    await service.ensure_ready(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        policy=_dedicated_policy(),
        workdir_path=WORKDIR,
    )

    await service.suspend(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        workdir_path=WORKDIR,
        reason="manual",
    )
    await service.suspend(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        workdir_path=WORKDIR,
        reason="manual",
    )

    row = await _get_row(session)
    assert row.status == "suspended"
    assert row.generation is None
    assert row.suspended_at is not None
    assert provider.release_calls == ["agent-project:user-1:coder:project-1"]


async def test_ensure_ready_rejects_shared_policy(session):
    provider = _FakeProvider()
    service = SandboxLifecycleService(session, provider=provider)

    with pytest.raises(ValueError, match="dedicated"):
        await service.ensure_ready(
            uid="user-1",
            agent_slug="coder",
            project_id="project-1",
            policy=SandboxPolicy(),
            workdir_path=WORKDIR,
        )


async def test_resolve_agent_sandbox_policy_merges_project_override(session):
    session.add(
        ProjectAgent(
            id="pa-1",
            project_id="project-1",
            agent_slug="coder",
            config_overrides={"sandbox": {"lifecycle": "resident", "idle_suspend_seconds": 600}},
        )
    )
    await session.flush()

    policy = await resolve_agent_sandbox_policy(
        db=session,
        agent_config={"sandbox": {"mode": "dedicated", "lifecycle": "persistent"}},
        agent_slug="coder",
        project_id="project-1",
    )

    assert policy.mode == "dedicated"
    assert policy.lifecycle == "resident"
    assert policy.idle_suspend_seconds == 600


async def test_resolve_agent_sandbox_policy_defaults_without_config(session):
    policy = await resolve_agent_sandbox_policy(
        db=session, agent_config=None, agent_slug="coder", project_id=None
    )

    assert policy.mode == "shared"
    assert policy.lifecycle == "ephemeral"


async def test_runtime_scope_for_policy_keeps_thread_for_shared():
    policy = SandboxPolicy()

    scope_id = runtime_scope_for_policy(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        conversation_thread_id="thread-1",
        policy=policy,
    )

    assert scope_id == "thread-1"


async def test_resolve_dispatch_runtime_scope_uses_dedicated_policy(session):
    session.add(
        Agent(
            slug="coder",
            backend_id="chatbot",
            name="Coder",
            pics=[],
            config_json={"sandbox": {"mode": "dedicated"}},
            share_config={},
            is_default=False,
            is_subagent=False,
        )
    )
    await session.flush()

    scope_id = await resolve_dispatch_runtime_scope(
        db=session,
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        conversation_thread_id="thread-1",
    )

    assert scope_id == "agent-project:user-1:coder:project-1"


async def test_resolve_dispatch_runtime_scope_defaults_to_thread(session):
    session.add(
        Agent(
            slug="coder",
            backend_id="chatbot",
            name="Coder",
            pics=[],
            config_json={},
            share_config={},
            is_default=False,
            is_subagent=False,
        )
    )
    await session.flush()

    scope_id = await resolve_dispatch_runtime_scope(
        db=session,
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        conversation_thread_id="thread-1",
    )

    assert scope_id == "thread-1"
