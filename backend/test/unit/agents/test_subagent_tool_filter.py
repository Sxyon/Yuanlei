from __future__ import annotations

from types import SimpleNamespace

import pytest
from deepagents.backends import StateBackend
from yuxi.agents.backends import create_agent_filesystem_middleware
from yuxi.agents.buildin.subagent import graph as subagent_graph


class _Request:
    def __init__(self, tools):
        self.tools = tools

    def override(self, **kwargs):
        return _Request(kwargs.get("tools", self.tools))


def test_filter_disabled_tools_keeps_allowed_tools_order():
    tools = [
        SimpleNamespace(name="search"),
        SimpleNamespace(name="present_artifacts"),
        {"name": "ask_user_question"},
        SimpleNamespace(name="install_skill"),
        SimpleNamespace(name="calculator"),
    ]

    filtered = subagent_graph._filter_disabled_tools(tools, subagent_graph._disabled_tools_for("default"))

    assert [subagent_graph._tool_name(tool) for tool in filtered] == ["search", "calculator"]


def test_filter_disabled_tools_removes_sensitive_backend_tools_only_in_default_mode():
    tools = [
        SimpleNamespace(name="read_file"),
        SimpleNamespace(name="write_file"),
        SimpleNamespace(name="edit_file"),
        SimpleNamespace(name="execute"),
        SimpleNamespace(name="git_list_project_repositories"),
        SimpleNamespace(name="git_prepare_worktree"),
        SimpleNamespace(name="git_push_branch"),
    ]

    default_mode_filtered = subagent_graph._filter_disabled_tools(tools, subagent_graph._disabled_tools_for("default"))
    assert [subagent_graph._tool_name(tool) for tool in default_mode_filtered] == ["read_file"]

    always_trust_filtered = subagent_graph._filter_disabled_tools(
        tools, subagent_graph._disabled_tools_for("always_trust")
    )
    assert [subagent_graph._tool_name(tool) for tool in always_trust_filtered] == [
        "read_file",
        "write_file",
        "edit_file",
        "execute",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_subagent_tool_filter_middleware_filters_before_handler(use_async: bool):
    middleware = subagent_graph._SubAgentToolFilterMiddleware()
    seen = {}

    async def async_handler(request):
        seen["tools"] = request.tools
        return "ok"

    def sync_handler(request):
        seen["tools"] = request.tools
        return "ok"

    request = _Request(
        [
            SimpleNamespace(name="present_artifacts"),
            {"name": "ask_user_question"},
            SimpleNamespace(name="allowed_tool"),
        ]
    )
    if use_async:
        result = await middleware.awrap_model_call(request, async_handler)
    else:
        result = middleware.wrap_model_call(request, sync_handler)

    assert result == "ok"
    assert [subagent_graph._tool_name(tool) for tool in seen["tools"]] == ["allowed_tool"]


@pytest.mark.asyncio
async def test_subagent_get_info_hides_disabled_tool_options(monkeypatch):
    async def get_info(_self, **_kwargs):
        return {
            "metadata": {},
            "configurable_items": {
                "tools": {
                    "options": [
                        {"key": "present_artifacts", "name": "展示交付物"},
                        {"key": "allowed_tool", "name": "Allowed"},
                        {"key": "ask_user_question", "name": "向用户提问"},
                        {"key": "install_skill", "name": "安装技能"},
                    ]
                }
            },
        }

    monkeypatch.setattr(subagent_graph.BaseAgent, "get_info", get_info)

    info = await subagent_graph.SubAgentBackend().get_info()

    assert [option["key"] for option in info["configurable_items"]["tools"]["options"]] == ["allowed_tool"]


class _ToolCallRequest:
    def __init__(self, name: str, call_id: str = "call_1"):
        self.tool_call = {"name": name, "args": {}, "id": call_id}


def test_filesystem_middleware_does_not_register_disabled_tools_in_default_mode():
    """默认模式下敏感工具必须不进入 ToolNode，否则隐藏只是对模型不可见。"""
    backend = StateBackend()

    default_mode = create_agent_filesystem_middleware(
        backend=backend, disabled_tools=subagent_graph._disabled_tools_for("default")
    )
    default_mode_names = {tool.name for tool in default_mode.tools}
    assert {"write_file", "edit_file", "execute"}.isdisjoint(default_mode_names)
    assert "read_file" in default_mode_names

    always_trust = create_agent_filesystem_middleware(
        backend=backend, disabled_tools=subagent_graph._disabled_tools_for("always_trust")
    )
    assert {"write_file", "edit_file", "execute"} <= {tool.name for tool in always_trust.tools}


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_subagent_tool_filter_middleware_denies_disabled_tool_execution(use_async: bool):
    """隐藏的工具即使被再次调用（续跑历史、补全或幻觉）也必须在执行前拒绝。"""
    middleware = subagent_graph._SubAgentToolFilterMiddleware("default")
    executed = []

    async def async_handler(request):
        executed.append(request.tool_call["name"])
        return "executed"

    def sync_handler(request):
        executed.append(request.tool_call["name"])
        return "executed"

    request = _ToolCallRequest("write_file")
    if use_async:
        result = await middleware.awrap_tool_call(request, async_handler)
    else:
        result = middleware.wrap_tool_call(request, sync_handler)

    assert executed == []
    assert result.status == "error"
    assert result.tool_call_id == "call_1"
    assert "write_file" in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name",
    ["git_list_project_repositories", "git_prepare_worktree", "git_push_branch"],
)
async def test_subagent_execution_denies_every_project_git_management_tool(tool_name: str):
    """模型可见性之外，执行拦截必须拒绝全部 Project Git 管理能力。"""
    middleware = subagent_graph._SubAgentToolFilterMiddleware("always_trust")
    executed = []

    async def handler(request):
        executed.append(request.tool_call["name"])
        return "executed"

    result = await middleware.awrap_tool_call(_ToolCallRequest(tool_name), handler)

    assert executed == []
    assert result.status == "error"
    assert tool_name in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_subagent_tool_filter_middleware_allows_enabled_tool_execution(use_async: bool):
    middleware = subagent_graph._SubAgentToolFilterMiddleware("default")
    executed = []

    async def async_handler(request):
        executed.append(request.tool_call["name"])
        return "executed"

    def sync_handler(request):
        executed.append(request.tool_call["name"])
        return "executed"

    request = _ToolCallRequest("read_file")
    if use_async:
        result = await middleware.awrap_tool_call(request, async_handler)
    else:
        result = middleware.wrap_tool_call(request, sync_handler)

    assert executed == ["read_file"]
    assert result == "executed"


@pytest.mark.asyncio
async def test_subagent_tool_filter_middleware_allows_sensitive_tools_in_always_trust():
    middleware = subagent_graph._SubAgentToolFilterMiddleware("always_trust")
    executed = []

    async def handler(request):
        executed.append(request.tool_call["name"])
        return "executed"

    result = await middleware.awrap_tool_call(_ToolCallRequest("write_file"), handler)

    assert executed == ["write_file"]
    assert result == "executed"
