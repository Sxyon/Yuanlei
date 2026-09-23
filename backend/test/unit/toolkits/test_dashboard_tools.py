"""Dashboard Agent 工具的注册与运行范围单元测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langgraph.prebuilt.tool_node import ToolRuntime

from yuxi.agents.toolkits.buildin import dashboard_tools
from yuxi.agents.toolkits.buildin.dashboard_tools import dashboard_read, dashboard_write
from yuxi.agents.toolkits.registry import get_all_tool_instances, get_extra_metadata
from yuxi.agents.toolkits.service import _extract_tool_info, get_tool_metadata, resolve_configured_runtime_tools

pytestmark = pytest.mark.unit


def test_dashboard_tools_registered_as_buildin():
    names = {getattr(item, "name", None) for item in get_all_tool_instances()}
    assert {"dashboard_read", "dashboard_write"} <= names
    assert get_extra_metadata("dashboard_read").category == "buildin"
    assert get_extra_metadata("dashboard_write").category == "buildin"


def test_dashboard_tools_have_serializable_metadata():
    """工具配置页必须能读取 Dashboard 工具，而不把 runtime 展开为输入 schema。"""
    metadata = {item["slug"]: item for item in get_tool_metadata(category="buildin")}
    assert metadata["dashboard_read"]["args"] == []
    assert [item["name"] for item in metadata["dashboard_write"]["args"]] == [
        "html",
        "expected_revision",
    ]
    assert "runtime" in dashboard_read.args_schema.model_fields
    assert "runtime" in dashboard_write.args_schema.model_fields
    assert dashboard_read.tool_call_schema.model_json_schema()["properties"] == {}
    assert set(dashboard_write.tool_call_schema.model_json_schema()["properties"]) == {
        "html",
        "expected_revision",
    }


def test_tool_metadata_preserves_a_business_parameter_named_runtime():
    """只有 ToolRuntime 注入参数可从配置元数据中省略。"""
    tool = SimpleNamespace(
        name="business_runtime",
        description="test",
        metadata={},
        args_schema=SimpleNamespace(
            model_fields={
                "runtime": SimpleNamespace(annotation=str, description="业务运行模式"),
            }
        ),
    )
    assert _extract_tool_info(tool)["args"] == [
        {"name": "runtime", "type": "str", "description": "业务运行模式"}
    ]


@pytest.mark.asyncio
async def test_dashboard_tool_preserves_injected_runtime(monkeypatch):
    """runtime 必须穿过 StructuredTool 的参数校验并到达执行函数。"""
    received = {}
    runtime = ToolRuntime(
        state={},
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-1",
        store=None,
    )

    async def fake_operation(actual_runtime, _operation):
        received["runtime"] = actual_runtime
        return "{\"status\": \"ok\"}"

    monkeypatch.setattr(dashboard_tools, "_run_dashboard_operation", fake_operation)

    assert await dashboard_read.ainvoke({"runtime": runtime}) == '{"status": "ok"}'
    assert received["runtime"] is runtime


@pytest.mark.asyncio
async def test_dashboard_read_tool_node_injects_runtime():
    """ToolNode 调用不得因 runtime 在 schema 校验中丢失而抛出 TypeError。"""
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([dashboard_read]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    result = await graph.compile().ainvoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "call-1", "name": "dashboard_read", "args": {}}],
                )
            ]
        }
    )

    payload = json.loads(result["messages"][-1].content)
    assert payload == {"error_code": "invalid_request", "message": "当前运行缺少 Project 上下文"}


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
