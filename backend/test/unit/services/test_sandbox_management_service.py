from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.repositories.agent_sandbox_repository import AgentSandboxRepository
from yuxi.services.coding_credential_service import (
    CodingCredentialService,
    CodingCredentialWrite,
)
from yuxi.services.sandbox_management_service import SandboxManagementService
from yuxi.storage.postgres.models_business import (
    Agent,
    AgentSandboxEvent,
    Base,
    Project,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

WORKDIR = "projects/11111111-1111-4111-8111-111111111111"
SCOPE_KEY = "agent-project:user-1:coder:project-1"
MASTER_KEY = base64.urlsafe_b64encode(b"0" * 32).decode().rstrip("=")


class _FakeProvider:
    def __init__(self):
        self.connections: dict[str, object] = {}
        self.created: list[str] = []
        self.released: list[str] = []

    def get_scope(self, scope, *, create_if_missing=False, **_kwargs):
        if scope.cache_key in self.connections:
            return self.connections[scope.cache_key]
        if not create_if_missing:
            return None
        self.created.append(scope.cache_key)
        connection = SimpleNamespace(
            cache_key=scope.cache_key,
            sandbox_id=scope.sandbox_id,
            generation=f"gen-{len(self.created)}",
            workdir_path=_kwargs.get("workdir_path"),
        )
        self.connections[scope.cache_key] = connection
        return connection

    def release_scope(self, scope, **_kwargs):
        self.released.append(scope.cache_key)
        self.connections.pop(scope.cache_key, None)

    def touch(self, _sandbox_id):
        return True

    def list_sandboxes(self):
        return list(self.connections.values())


@pytest_asyncio.fixture()
async def session(monkeypatch):
    monkeypatch.setenv("YUXI_CODING_CREDENTIAL_KEY", MASTER_KEY)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _seed(session, *, status="active"):
    session.add(
        Project(
            id="project-1",
            uid="user-1",
            selection_status="implicit",
            workdir_path=WORKDIR,
            directory_mode="managed",
        )
    )
    session.add(
        Agent(
            slug="coder",
            backend_id="ChatbotAgent",
            name="Coder",
            pics=[],
            config_json={
                "sandbox": {"mode": "dedicated", "lifecycle": "persistent"},
                "coding": {"executors": ["opencode"]},
            },
            share_config={},
            is_default=False,
            is_subagent=False,
        )
    )
    await session.flush()
    row = await AgentSandboxRepository(session).add(
        uid="user-1",
        agent_slug="coder",
        project_id="project-1",
        scope_key=SCOPE_KEY,
        sandbox_id="abc123abc123",
        lifecycle="persistent",
        resume_policy="auto",
        idle_timeout_seconds=1800,
    )
    row.generation = "gen-seed"
    row.status = status
    await session.flush()
    return row


async def test_list_reports_quota_and_usage(session):
    await _seed(session)

    listing = await SandboxManagementService(session, provider=_FakeProvider()).list_user_sandboxes(
        uid="user-1"
    )

    assert listing["quota"]["dedicated_used"] == 1
    assert listing["quota"]["active"] == 1
    assert listing["sandboxes"][0]["agent_slug"] == "coder"
    assert listing["sandboxes"][0]["generation"] == "gen-seed"


async def test_manual_suspend_marks_suspended_and_records_event(session):
    row = await _seed(session)
    provider = _FakeProvider()
    provider.connections[SCOPE_KEY] = SimpleNamespace(
        cache_key=SCOPE_KEY, sandbox_id=row.sandbox_id, generation="gen-seed", workdir_path=WORKDIR
    )

    view = await SandboxManagementService(session, provider=provider).suspend(
        uid="user-1", agent_slug="coder", project_id="project-1"
    )

    assert view["status"] == "suspended"
    assert provider.released == [SCOPE_KEY]
    events = (await session.execute(select(AgentSandboxEvent))).scalars().all()
    assert any(event.kind == "suspended" and event.payload_json.get("reason") == "manual_suspend" for event in events)


async def test_manual_rebuild_recreates_runtime_with_new_generation(session):
    await _seed(session)
    await CodingCredentialService(session).upsert(
        scope="user",
        uid="user-1",
        payload=CodingCredentialWrite(executor="opencode", provider="sf", api_key="sk-rebuild"),
        actor="user-1",
    )
    provider = _FakeProvider()

    view = await SandboxManagementService(session, provider=provider).rebuild(
        uid="user-1", agent_slug="coder", project_id="project-1"
    )

    assert view["status"] == "active"
    assert view["generation"] == "gen-1"
    assert provider.created == [SCOPE_KEY]
    assert view["credential_fingerprint"]


async def test_manual_operations_reject_foreign_project(session):
    await _seed(session)

    with pytest.raises(ValueError, match="project not found"):
        await SandboxManagementService(session, provider=_FakeProvider()).suspend(
            uid="user-2", agent_slug="coder", project_id="project-1"
        )
