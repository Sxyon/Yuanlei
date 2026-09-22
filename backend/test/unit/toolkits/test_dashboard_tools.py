"""Dashboard Agent 工具的注册与运行范围单元测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yuxi.agents.toolkits.buildin.dashboard_tools import dashboard_read, dashboard_write
from yuxi.agents.toolkits.registry import get_all_tool_instances, get_extra_metadata
from yuxi.agents.toolkits.service import resolve_configured_runtime_tools

pytestmark = pytest.mark.unit


def test_dashboard_tools_registered_as_buildin():
    names = {getattr(item, "name", None) for item in get_all_tool_instances()}
    assert {"dashboard_read", "dashboard_write"} <= names
    assert get_extra_metadata("dashboard_read").category == "buildin"
    assert get_extra_metadata("dashboard_write").category == "buildin"


@pytest.mark.asyncio
async def test_dashboard_tools_require_explicit_agent_selection():
    context = SimpleNamespace(
        tools=["dashboard_read", "dashboard_write"],
        mcps=[],
        coding_executors=[],
        project_git_enabled=False,
        _skill_runtime_snapshot={},
    )
    selected = await resolve_configured_runtime_tools(context)
    assert [item.name for item in selected] == ["dashboard_read", "dashboard_write"]


@pytest.mark.asyncio
async def test_dashboard_operation_rejects_subagent_runtime():
    runtime = SimpleNamespace(context=SimpleNamespace(is_subagent_runtime=True, run_id="run-1", uid="uid-1"))
    payload = json.loads(await dashboard_read.coroutine(runtime=runtime))
    assert payload == {"error_code": "invalid_request", "message": "子智能体不能读取或修改项目 Dashboard"}


@pytest.mark.asyncio
async def test_dashboard_operation_requires_run_context():
    runtime = SimpleNamespace(context=SimpleNamespace(is_subagent_runtime=False))
    payload = json.loads(await dashboard_write.coroutine(html="<html></html>", expected_revision=0, runtime=runtime))
    assert payload == {"error_code": "invalid_request", "message": "当前运行缺少 Project 上下文"}
