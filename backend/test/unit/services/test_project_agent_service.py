"""ProjectAgent 运行范围与配置覆盖的单元测试。"""

from __future__ import annotations

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
