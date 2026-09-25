"""子智能体委派工具的 fail-closed 守卫（不访问 DB、不发外部请求）。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from yuxi.agents.toolkits.buildin import delegation_tools

pytestmark = pytest.mark.asyncio


async def test_subagent_delegation_operation_fails_closed_without_db_or_external(monkeypatch: pytest.MonkeyPatch):
    """`is_subagent_runtime` 时结构化拒绝，且在打开会话前返回，不触发任何委派副作用。"""
    operation = AsyncMock()
    session_ctx = Mock(side_effect=AssertionError("子智能体不应打开数据库会话"))
    monkeypatch.setattr(delegation_tools.pg_manager, "get_async_session_context", session_ctx)

    runtime = SimpleNamespace(
        context=SimpleNamespace(
            is_subagent_runtime=True,
            run_id="run-1",
            uid="uid-1",
            worker_id="worker-1",
        )
    )

    result = await delegation_tools._run_delegation_operation(runtime, operation)

    payload = json.loads(result)
    assert payload["error_code"] == "invalid_request"
    assert "子智能体" in payload["message"]
    session_ctx.assert_not_called()
    operation.assert_not_awaited()
