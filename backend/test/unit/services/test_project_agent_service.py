"""ProjectAgent 运行范围与配置覆盖的单元测试。"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from yuxi.agents import context as agent_context
from yuxi.agents.context import BaseContext
from yuxi.services import project_agent_service as service


def _fake_binding_repository(*, project_ids: list[str], overrides: dict | None = None):
    """构造只返回固定绑定事实的 ProjectAgentRepository 替身。"""

    class _Repo:
        def __init__(self, _db):
            pass

        async def list_project_ids_for_agent(self, _agent_slug: str) -> list[str]:
            return list(project_ids)

        async def get(self, _project_id: str, _agent_slug: str):
            if overrides is None:
                return None
            return SimpleNamespace(config_overrides=overrides)

    return _Repo


@pytest.mark.asyncio
async def test_ensure_agent_project_scope_allows_unbound_agent(monkeypatch):
    monkeypatch.setattr(service, "ProjectAgentRepository", _fake_binding_repository(project_ids=[]))

    await service.ensure_agent_project_scope(db=object(), agent_slug="global-agent", project_id=None)
    await service.ensure_agent_project_scope(db=object(), agent_slug="global-agent", project_id="project-1")


@pytest.mark.asyncio
async def test_ensure_agent_project_scope_allows_only_bound_project(monkeypatch):
    monkeypatch.setattr(service, "ProjectAgentRepository", _fake_binding_repository(project_ids=["project-1"]))

    await service.ensure_agent_project_scope(db=object(), agent_slug="employee", project_id="project-1")
    with pytest.raises(service.AgentProjectScopeDenied):
        await service.ensure_agent_project_scope(db=object(), agent_slug="employee", project_id="project-2")
    with pytest.raises(service.AgentProjectScopeDenied):
        await service.ensure_agent_project_scope(db=object(), agent_slug="employee", project_id=None)


def test_load_agent_run_context_merges_project_override():
    """Run 创建快照读取项目覆盖的 model 与审批模式。"""
    from yuxi.services.agent_run_service import load_agent_run_context

    class _Context:
        model = "base-model"
        tool_approval_mode = "default"

        def update_config(self, values):
            for key, value in values.items():
                setattr(self, key, value)

    agent = SimpleNamespace(config_json={"context": {"model": "base-model"}})
    backend = SimpleNamespace(context_schema=_Context)

    context = load_agent_run_context(
        agent,
        backend,
        project_override={"model": "project-model", "tool_approval_mode": "always_trust"},
    )

    assert context.model == "project-model"
    assert context.tool_approval_mode == "always_trust"


@pytest.mark.asyncio
async def test_resolve_effective_agent_context_prefers_project_override(monkeypatch):
    resource_calls: list[object] = []

    async def no_resource_options(resource_fields=None, *, db, user):
        resource_calls.append(resource_fields)
        return {}

    monkeypatch.setattr(agent_context, "resolve_agent_resource_options", no_resource_options)
    monkeypatch.setattr(
        service,
        "ProjectAgentRepository",
        _fake_binding_repository(project_ids=["project-1"], overrides={"context": {"system_prompt": "项目人格"}}),
    )
    agent = SimpleNamespace(slug="employee", config_json={"context": {"system_prompt": "基础人格"}})
    user = SimpleNamespace(uid="uid-1", role="user")

    context = await service.resolve_effective_agent_context(
        agent_item=agent,
        project_id="project-1",
        db=object(),
        user=user,
        context_schema=BaseContext,
    )

    assert context["system_prompt"] == "项目人格"
    assert resource_calls == [{"tools", "knowledges", "mcps", "skills"}]


@pytest.mark.asyncio
async def test_resolve_effective_agent_context_without_binding_uses_base(monkeypatch):
    async def no_resource_options(resource_fields=None, *, db, user):
        return {}

    monkeypatch.setattr(agent_context, "resolve_agent_resource_options", no_resource_options)
    monkeypatch.setattr(
        service,
        "ProjectAgentRepository",
        _fake_binding_repository(project_ids=[], overrides=None),
    )
    agent = SimpleNamespace(slug="global-agent", config_json={"context": {"system_prompt": "基础人格"}})
    user = SimpleNamespace(uid="uid-1", role="user")

    context = await service.resolve_effective_agent_context(
        agent_item=agent,
        project_id=None,
        db=object(),
        user=user,
        context_schema=BaseContext,
    )

    assert context["system_prompt"] == "基础人格"


class _FakeDb:
    """记录提交结果的最小会话替身。"""

    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True

    async def refresh(self, _item):
        return None


def _install_update_fakes(monkeypatch, *, overrides: dict, context_schema, captured: dict) -> None:
    """替身仓储与依赖，并捕获被修改的 binding。"""

    class _AgentRepo:
        def __init__(self, _db):
            pass

        async def get_visible_by_slug(self, **_kwargs):
            return SimpleNamespace(
                slug="employee", backend_id="ChatbotAgent", config_json={"context": {}}
            )

    class _BindingRepo:
        def __init__(self, _db):
            pass

        async def get_for_update(self, _project_id: str, _agent_slug: str):
            binding = SimpleNamespace(
                config_overrides=copy.deepcopy(overrides), updated_by=None, updated_at=None
            )
            captured["binding"] = binding
            return binding

    async def fake_lock(**_kwargs):
        return SimpleNamespace(id="project-1")

    async def fake_serialize(**_kwargs):
        return {}

    monkeypatch.setattr(service, "_lock_manageable_project", fake_lock)
    monkeypatch.setattr(service, "AgentRepository", _AgentRepo)
    monkeypatch.setattr(service, "ProjectAgentRepository", _BindingRepo)
    monkeypatch.setattr(service, "user_can_manage_agent", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        service,
        "get_agent_backend",
        lambda _backend_id: SimpleNamespace(context_schema=context_schema),
    )
    monkeypatch.setattr(service, "_serialize_binding", fake_serialize)


async def _run_update_view(monkeypatch, *, overrides, reset_fields, context_schema, captured) -> None:
    _install_update_fakes(
        monkeypatch, overrides=overrides, context_schema=context_schema, captured=captured
    )
    db = _FakeDb()
    await service.update_project_agent_view(
        project_id="project-1",
        agent_slug="employee",
        config_json={},
        reset_fields=reset_fields,
        db=db,
        user=SimpleNamespace(uid="user-1", role="user"),
    )
    assert db.committed


@dataclass
class _ResetContext:
    """覆盖保存 reset 语义的最小 Schema。"""

    model: str = ""
    title: str = ""


@pytest.mark.asyncio
async def test_update_project_agent_view_resets_execution_sections(monkeypatch):
    """reset_fields 支持 sandbox/coding 整段恢复继承，同时保留 context 覆盖。"""
    captured: dict = {}
    await _run_update_view(
        monkeypatch,
        overrides={
            "context": {"model": "project-model"},
            "sandbox": {"mode": "dedicated", "lifecycle": "persistent"},
            "coding": {"executors": ["opencode"]},
        },
        reset_fields=["sandbox", "coding"],
        context_schema=BaseContext,
        captured=captured,
    )

    assert captured["binding"].config_overrides == {"context": {"model": "project-model"}}


@pytest.mark.asyncio
async def test_update_project_agent_view_reset_keeps_other_sections(monkeypatch):
    """重置 context 字段不影响 sandbox/coding 覆盖层。"""
    captured: dict = {}
    await _run_update_view(
        monkeypatch,
        overrides={
            "context": {"model": "project-model", "title": "keep"},
            "sandbox": {"mode": "dedicated"},
        },
        reset_fields=["model"],
        context_schema=_ResetContext,
        captured=captured,
    )

    assert captured["binding"].config_overrides == {
        "context": {"title": "keep"},
        "sandbox": {"mode": "dedicated"},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("child", [False, True])
async def test_task_knowledge_selection_uses_persisted_root_thread(monkeypatch, child):
    """普通续聊和子智能体使用同一持久任务选择，不依赖请求来源。"""
    from unittest.mock import AsyncMock

    root = SimpleNamespace(id="root", run_type="chat", source="chat", conversation_thread_id="task-thread")
    run = SimpleNamespace(id="child", run_type="subagent", created_by_run_id="root") if child else root
    lookup = AsyncMock(return_value=SimpleNamespace(knowledge_ids=["selected"]))
    parents = AsyncMock(return_value=root)
    monkeypatch.setattr(service, "ProjectWorkExecutionRepository", lambda db: SimpleNamespace(task_for_thread=lookup, context_for_thread=AsyncMock(return_value=None)))
    monkeypatch.setattr(service, "AgentRunRepository", lambda db: SimpleNamespace(get_run_for_user=parents))
    assert await service.load_task_knowledge_selection(db=object(), uid="user", project_id="project", run=run) == [
        "selected"
    ]
    lookup.assert_awaited_once_with(thread_id="task-thread", project_id="project", uid="user")
    if child:
        parents.assert_awaited_once_with("root", "user")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_parent", "foreign_parent", "cycle"])
async def test_task_knowledge_selection_rejects_invalid_parent(monkeypatch, failure):
    """父级缺失、越权和循环不能恢复其他运行的任务选择。"""
    from unittest.mock import AsyncMock

    run = SimpleNamespace(
        id="child", run_type="subagent", created_by_run_id=None if failure == "missing_parent" else "parent"
    )
    parent = None if failure == "foreign_parent" else run
    lookup = AsyncMock()
    monkeypatch.setattr(
        service, "AgentRunRepository", lambda db: SimpleNamespace(get_run_for_user=AsyncMock(return_value=parent))
    )
    monkeypatch.setattr(service, "ProjectWorkExecutionRepository", lambda db: SimpleNamespace(task_for_thread=lookup, context_for_thread=AsyncMock(return_value=None)))
    with pytest.raises(PermissionError if failure == "foreign_parent" else ValueError):
        await service.load_task_knowledge_selection(db=object(), uid="user", project_id="project", run=run)
    lookup.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("visible,linked", [({"frozen"}, {"frozen"}), (set(), {"frozen"}), ({"frozen"}, set())])
async def test_frozen_knowledge_is_not_silently_removed(monkeypatch, visible, linked):
    """固化知识库保持选取，撤权及取消关联显式拒绝运行。"""
    from unittest.mock import AsyncMock

    snapshot = {"knowledge_ids": ["frozen"]}
    monkeypatch.setattr(service, "ProjectWorkExecutionRepository", lambda db: SimpleNamespace(
        task_for_thread=AsyncMock(return_value=SimpleNamespace(knowledge_ids=["new"])),
        context_for_thread=AsyncMock(return_value=SimpleNamespace(context_snapshot=snapshot))))
    monkeypatch.setattr(service, "UserRepository", lambda: SimpleNamespace(get_by_uid_with_db=AsyncMock(return_value=object())))
    monkeypatch.setattr(service, "ProjectSettingsRepository", lambda db: SimpleNamespace(
        knowledge=AsyncMock(return_value=([], visible)), linked_ids=AsyncMock(return_value=list(linked))))
    run = SimpleNamespace(id="r", run_type="chat", conversation_thread_id="thread")
    if visible and linked:
        assert await service.load_task_knowledge_selection(db=object(), uid="u", project_id="p", run=run) == ["frozen"]
    else:
        with pytest.raises(PermissionError, match="撤权"):
            await service.load_task_knowledge_selection(db=object(), uid="u", project_id="p", run=run)
    assert snapshot == {"knowledge_ids": ["frozen"]}
