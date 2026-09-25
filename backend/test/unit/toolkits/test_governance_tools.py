"""督查板与治理 Agent 工具的注册、元数据与错误收敛单元测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langgraph.prebuilt.tool_node import ToolRuntime

from yuxi.agents.toolkits.buildin import governance_tools
from yuxi.agents.toolkits.buildin.governance_tools import (
    governance_board_read,
    governance_topic_open,
)
from yuxi.agents.toolkits.registry import get_all_tool_instances, get_extra_metadata
from yuxi.agents.toolkits.service import get_tool_metadata

pytestmark = pytest.mark.unit

GOVERNANCE_TOOL_NAMES = (
    "governance_board_read",
    "governance_report_write",
    "governance_topic_open",
)


def _runtime(context) -> ToolRuntime:
    return ToolRuntime(
        state={},
        context=context,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-1",
        store=None,
    )


def test_governance_tools_registered_as_buildin():
    names = {getattr(item, "name", None) for item in get_all_tool_instances()}
    assert set(GOVERNANCE_TOOL_NAMES) <= names
    for name in GOVERNANCE_TOOL_NAMES:
        assert get_extra_metadata(name).category == "buildin"


def test_governance_tools_have_serializable_metadata():
    """工具配置页必须能读取治理工具，而不把 runtime 展开为输入 schema。"""
    metadata = {item["slug"]: item for item in get_tool_metadata(category="buildin")}
    assert metadata["governance_board_read"]["args"] == []
    assert [item["name"] for item in metadata["governance_report_write"]["args"]] == [
        "title",
        "summary",
        "content_json",
        "artifact_path",
    ]
    assert [item["name"] for item in metadata["governance_topic_open"]["args"]] == [
        "title",
        "summary",
    ]
    assert "runtime" in governance_board_read.args_schema.model_fields
    assert governance_board_read.tool_call_schema.model_json_schema()["properties"] == {}


@pytest.mark.asyncio
async def test_governance_tool_preserves_injected_runtime(monkeypatch):
    """runtime 必须穿过 StructuredTool 的参数校验并到达执行函数。"""
    received = {}
    runtime = _runtime(context=None)

    async def fake_operation(actual_runtime, _operation):
        received["runtime"] = actual_runtime
        return '{"status": "ok"}'

    monkeypatch.setattr(governance_tools, "_run_governance_operation", fake_operation)

    assert await governance_topic_open.ainvoke({"title": "议题", "runtime": runtime}) == '{"status": "ok"}'
    assert received["runtime"] is runtime


@pytest.mark.asyncio
async def test_governance_tool_rejects_subagent_runtime():
    """子智能体运行不得读取督查板或写入治理事实。"""
    runtime = _runtime(context=SimpleNamespace(is_subagent_runtime=True))
    result = await governance_board_read.ainvoke({"runtime": runtime})
    assert '"error_code": "invalid_request"' in result
    assert "子智能体" in result
