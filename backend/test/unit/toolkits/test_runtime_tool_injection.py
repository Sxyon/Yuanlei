"""运行时工具注入的幂等回归：Skill 门控与编码注入不得因同实例重复注册而冲突。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yuxi.agents.toolkits.service import resolve_configured_runtime_tools

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]


async def test_coding_tools_are_not_duplicated_when_skill_gated():
    """编码工具被 Skill 门控先注册后，运行时注入应跳过同一实例而不是报冲突。"""
    from yuxi.agents.toolkits.buildin.coding_tools import coding_session_start

    context = SimpleNamespace(
        tools=[],
        mcps=[],
        project_git_enabled=False,
        coding_executors=["opencode"],
        _skill_runtime_snapshot={
            "runtime_skills": {
                "coding-executor": {"tools": ["coding_session_start"]},
            },
            "effective_skills": ["coding-executor"],
        },
    )

    tools = await resolve_configured_runtime_tools(context)

    matched = [tool for tool in tools if tool.name == "coding_session_start"]
    assert len(matched) == 1
    assert matched[0] is coding_session_start
    assert len({tool.name for tool in tools}) == len(tools)
