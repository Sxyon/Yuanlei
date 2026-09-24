from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.repositories.agent_sandbox_repository import AgentSandboxRepository
from yuxi.services import sandbox_management_service as service
from yuxi.services.coding_credential_service import (
    CodingCredentialService,
    CodingCredentialWrite,
)
from yuxi.services.sandbox_management_service import SandboxManagementService
from yuxi.storage.postgres.models_business import (
    Agent,
    AgentSandbox,
    AgentSandboxEvent,
    Base,
    Project,
    ProjectAgent,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

WORKDIR = "projects/11111111-1111-4111-8111-111111111111"
SCOPE_KEY = "agent-project:user-1:coder:project-1"
MASTER_KEY = base64.urlsafe_b64encode(b"0" * 32).decode().rstrip("=")


class _FakeProvider:
    def __init__(self):
        self.connections: dict[str, object] = {}
        self.created: list[str] = []
        self.created_calls: list[dict] = []
        self.released: list[str] = []

    def get_scope(self, scope, *, create_if_missing=False, **_kwargs):
        if scope.cache_key in self.connections:
            return self.connections[scope.cache_key]
        if not create_if_missing:
            return None
        self.created.append(scope.cache_key)
        self.created_calls.append(
            {
                "scope": scope,
                "lifecycle": _kwargs.get("lifecycle"),
                "idle_timeout_seconds": _kwargs.get("idle_timeout_seconds"),
                "workdir_path": _kwargs.get("workdir_path"),
                "env_overrides": _kwargs.get("env_overrides"),
            }
        )
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


@pytest.fixture(autouse=True)
def _stub_skill_projection(monkeypatch):
    """单元测试不触达真实 Skill 投影存储。"""

    async def noop(_uid: str) -> dict:
        return {}

    monkeypatch.setattr(service, "refresh_user_skill_projection_async", noop)


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


async def _seed_agent_project(session, *, sandbox_config: dict, overrides: dict | None = None) -> None:
    """预置 Project 与 Agent（不创建沙盒记录），用于预热路径。"""
    session.add(
        Project(
            id="project-1",
            uid="user-1",
            selection_status="selectable",
            workdir_path=WORKDIR,
            directory_mode="linked",
            status="active",
        )
    )
    session.add(
        Agent(
            slug="coder",
            backend_id="ChatbotAgent",
            name="Coder",
            pics=[],
            config_json=sandbox_config,
            share_config={},
            is_default=False,
            is_subagent=False,
        )
    )
    if overrides is not None:
        session.add(
            ProjectAgent(
                id="pa-1",
                project_id="project-1",
                agent_slug="coder",
                config_overrides=overrides,
            )
        )
    await session.flush()


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


async def test_provision_creates_dedicated_sandbox(session):
    """预热为新绑定创建专属沙盒，并使用项目 Workdir。"""
    await _seed_agent_project(
        session, sandbox_config={"sandbox": {"mode": "dedicated", "lifecycle": "persistent"}}
    )
    provider = _FakeProvider()

    view = await SandboxManagementService(session, provider=provider).provision(
        uid="user-1", agent_slug="coder", project_id="project-1"
    )

    assert view["status"] == "active"
    assert view["lifecycle"] == "persistent"
    assert view["generation"] == "gen-1"
    assert provider.created_calls[0]["workdir_path"] == WORKDIR
    row = (await session.execute(select(AgentSandbox))).scalars().one()
    assert row.uid == "user-1"
    assert row.scope_key == SCOPE_KEY


async def test_provision_reuses_existing_runtime(session):
    """重复预热复用已有 runtime，不重复创建。"""
    await _seed_agent_project(
        session, sandbox_config={"sandbox": {"mode": "dedicated", "lifecycle": "persistent"}}
    )
    provider = _FakeProvider()
    management = SandboxManagementService(session, provider=provider)

    first = await management.provision(uid="user-1", agent_slug="coder", project_id="project-1")
    second = await management.provision(uid="user-1", agent_slug="coder", project_id="project-1")

    assert len(provider.created) == 1
    assert second["generation"] == first["generation"]


async def test_provision_applies_project_override_policy(session):
    """项目覆盖层的生命周期策略在预热时生效。"""
    await _seed_agent_project(
        session,
        sandbox_config={"sandbox": {"mode": "dedicated", "lifecycle": "persistent"}},
        overrides={"sandbox": {"lifecycle": "resident", "idle_suspend_seconds": 0}},
    )
    provider = _FakeProvider()

    view = await SandboxManagementService(session, provider=provider).provision(
        uid="user-1", agent_slug="coder", project_id="project-1"
    )

    assert view["lifecycle"] == "resident"
    assert provider.created_calls[0]["idle_timeout_seconds"] == 0


async def test_provision_rejects_shared_policy(session):
    """共享策略不允许预热专属沙盒。"""
    await _seed_agent_project(session, sandbox_config={"sandbox": {"mode": "shared"}})

    with pytest.raises(ValueError, match="dedicated"):
        await SandboxManagementService(session, provider=_FakeProvider()).provision(
            uid="user-1", agent_slug="coder", project_id="project-1"
        )


async def test_provision_rejects_foreign_project(session):
    """预热只允许作用于自己拥有的项目。"""
    await _seed_agent_project(
        session, sandbox_config={"sandbox": {"mode": "dedicated", "lifecycle": "persistent"}}
    )

    with pytest.raises(ValueError, match="project not found"):
        await SandboxManagementService(session, provider=_FakeProvider()).provision(
            uid="user-2", agent_slug="coder", project_id="project-1"
        )


async def test_provision_refreshes_skill_projection_before_create(session, monkeypatch):
    """预热前先物化 Skill 投影，避免 provisioner 目录校验失败。"""
    await _seed_agent_project(
        session, sandbox_config={"sandbox": {"mode": "dedicated", "lifecycle": "persistent"}}
    )
    calls: list[str] = []

    async def record_refresh(uid: str) -> dict:
        calls.append(uid)
        return {}

    monkeypatch.setattr(service, "refresh_user_skill_projection_async", record_refresh)

    await SandboxManagementService(session, provider=_FakeProvider()).provision(
        uid="user-1", agent_slug="coder", project_id="project-1"
    )

    assert calls == ["user-1"]
