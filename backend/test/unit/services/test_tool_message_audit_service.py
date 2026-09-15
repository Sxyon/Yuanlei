from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from yuxi.services import tool_message_audit_service
from yuxi.services.tool_message_audit_service import ToolMessageAuditCollector


class _FakeDb:
    pass


@pytest.mark.asyncio
async def test_collector_projects_tool_start_and_successful_finish(monkeypatch):
    """Tool lifecycle 保存 effective input、严格顺序、输出和 monotonic 耗时。"""
    db = _FakeDb()
    calls: list[tuple[str, dict]] = []

    @asynccontextmanager
    async def session_context():
        yield db

    class FakeRepository:
        def __init__(self, _db):
            pass

        async def start(self, **kwargs):
            calls.append(("start", kwargs))
            return SimpleNamespace(id=1), True

        async def complete(self, **kwargs):
            calls.append(("complete", kwargs))
            return SimpleNamespace(id=1)

        async def fail(self, **kwargs):
            calls.append(("fail", kwargs))
            return SimpleNamespace(id=1)

    monotonic_values = iter([100.0, 100.275])
    monkeypatch.setattr(tool_message_audit_service.pg_manager, "get_async_session_context", session_context)
    monkeypatch.setattr(tool_message_audit_service, "ToolMessageAuditRepository", FakeRepository)
    monkeypatch.setattr(tool_message_audit_service, "monotonic", lambda: next(monotonic_values))

    collector = ToolMessageAuditCollector(
        run_id="run-1",
        request_id="request-1",
        thread_id="thread-1",
        worker_id="worker-1",
    )
    await collector.consume(
        {
            "method": "tools",
            "namespace": [],
            "seq": 11,
            "timestamp": 1_777_000_123_456,
            "data": {
                "event": "tool-started",
                "tool_call_id": "call-1",
                "tool_name": "search",
                "input": {"query": "effective input"},
            },
        }
    )
    output = {
        "type": "tool",
        "tool_call_id": "call-1",
        "content": [{"type": "text", "text": "result"}],
        "status": "success",
        "private_lifecycle_field": "audit-only",
    }
    await collector.consume(
        {
            "method": "tools",
            "namespace": [],
            "seq": 12,
            "timestamp": 1_777_000_123_789,
            "data": {"event": "tool-finished", "tool_call_id": "call-1", "output": output},
        }
    )

    assert calls[0] == (
        "start",
        {
            "run_id": "run-1",
            "request_id": "request-1",
            "thread_id": "thread-1",
            "worker_id": "worker-1",
            "tool_call_id": "call-1",
            "tool_name": "search",
            "tool_input": {"query": "effective input"},
            "sequence": 11,
            "started_at": calls[0][1]["started_at"],
            "metadata": {"namespace": []},
        },
    )
    assert calls[1] == (
        "complete",
        {
            "run_id": "run-1",
            "request_id": "request-1",
            "thread_id": "thread-1",
            "worker_id": "worker-1",
            "tool_call_id": "call-1",
            "output": output,
            "content": '[{"type": "text", "text": "result"}]',
            "finished_at": calls[1][1]["finished_at"],
            "duration_ms": 275,
            "finished_sequence": 12,
        },
    )


def test_tool_output_without_content_does_not_enter_compatibility_projection():
    """原始 lifecycle envelope 不得作为普通 ToolCall 输出。"""
    assert (
        tool_message_audit_service._tool_output_content(
            {"type": "tool", "status": "success", "private_lifecycle_field": "audit-only"}
        )
        == ""
    )


@pytest.mark.asyncio
async def test_duplicate_start_preserves_original_monotonic_clock(monkeypatch):
    """同一 collector 重放 start 不得清除首次观察到的 monotonic 起点。"""
    db = _FakeDb()
    durations: list[int | None] = []
    created_values = iter([True, False])

    @asynccontextmanager
    async def session_context():
        yield db

    class FakeRepository:
        def __init__(self, _db):
            pass

        async def start(self, **_kwargs):
            return SimpleNamespace(id=1), next(created_values)

        async def complete(self, **kwargs):
            durations.append(kwargs["duration_ms"])
            return SimpleNamespace(id=1)

    monotonic_values = iter([100.0, 100.1, 100.25])
    monkeypatch.setattr(tool_message_audit_service.pg_manager, "get_async_session_context", session_context)
    monkeypatch.setattr(tool_message_audit_service, "ToolMessageAuditRepository", FakeRepository)
    monkeypatch.setattr(tool_message_audit_service, "monotonic", lambda: next(monotonic_values))

    collector = ToolMessageAuditCollector(
        run_id="run-1",
        request_id="request-1",
        thread_id="thread-1",
        worker_id="worker-1",
    )
    start = {
        "method": "tools",
        "seq": 1,
        "timestamp": 1_777_000_123_456,
        "data": {
            "event": "tool-started",
            "tool_call_id": "call-1",
            "tool_name": "search",
            "input": {},
        },
    }
    await collector.consume(start)
    await collector.consume(start)
    await collector.consume(
        {
            "method": "tools",
            "seq": 2,
            "timestamp": 1_777_000_123_789,
            "data": {
                "event": "tool-finished",
                "tool_call_id": "call-1",
                "output": {"type": "tool", "content": "done", "status": "success"},
            },
        }
    )

    assert durations == [250]


@pytest.mark.asyncio
async def test_collector_treats_error_tool_message_as_failed_finish(monkeypatch):
    """ToolNode 包装为 tool-finished 的 error ToolMessage 仍必须保存为失败。"""
    db = _FakeDb()
    calls: list[tuple[str, dict]] = []

    @asynccontextmanager
    async def session_context():
        yield db

    class FakeRepository:
        def __init__(self, _db):
            pass

        async def start(self, **kwargs):
            calls.append(("start", kwargs))
            return SimpleNamespace(id=1), True

        async def fail(self, **kwargs):
            calls.append(("fail", kwargs))
            return SimpleNamespace(id=1)

    monkeypatch.setattr(tool_message_audit_service.pg_manager, "get_async_session_context", session_context)
    monkeypatch.setattr(tool_message_audit_service, "ToolMessageAuditRepository", FakeRepository)
    monkeypatch.setattr(tool_message_audit_service, "monotonic", lambda: 100.0)

    collector = ToolMessageAuditCollector(
        run_id="run-1",
        request_id="request-1",
        thread_id="thread-1",
        worker_id="worker-1",
    )
    await collector.consume(
        {
            "method": "tools",
            "seq": 1,
            "timestamp": 1_777_000_123_456,
            "data": {
                "event": "tool-started",
                "tool_call_id": "call-error",
                "tool_name": "search",
                "input": {},
            },
        }
    )
    output = {
        "type": "tool",
        "tool_call_id": "call-error",
        "content": "invalid arguments",
        "status": "error",
    }
    await collector.consume(
        {
            "method": "tools",
            "seq": 2,
            "timestamp": 1_777_000_123_789,
            "data": {"event": "tool-finished", "tool_call_id": "call-error", "output": output},
        }
    )

    assert calls[1][0] == "fail"
    assert calls[1][1]["error_message"] == "invalid arguments"
    assert calls[1][1]["content"] == "invalid arguments"


@pytest.mark.asyncio
async def test_raw_tool_error_waits_for_run_terminal(monkeypatch):
    """裸 tool-error 可能是 LangGraph interrupt，不能提前把 pending ToolCall 判为失败。"""
    db = _FakeDb()
    observed: list[dict] = []

    @asynccontextmanager
    async def session_context():
        yield db

    class FakeRepository:
        def __init__(self, _db):
            pass

        async def start(self, **_kwargs):
            return SimpleNamespace(id=1), True

        async def observe_error(self, **kwargs):
            observed.append(kwargs)
            return SimpleNamespace(id=1)

    monotonic_values = iter([100.0, 100.2])
    monkeypatch.setattr(tool_message_audit_service.pg_manager, "get_async_session_context", session_context)
    monkeypatch.setattr(tool_message_audit_service, "ToolMessageAuditRepository", FakeRepository)
    monkeypatch.setattr(tool_message_audit_service, "monotonic", lambda: next(monotonic_values))

    collector = ToolMessageAuditCollector(
        run_id="run-1",
        request_id="request-1",
        thread_id="thread-1",
        worker_id="worker-1",
    )
    await collector.consume(
        {
            "method": "tools",
            "seq": 1,
            "timestamp": 1_777_000_123_456,
            "data": {
                "event": "tool-started",
                "tool_call_id": "call-interrupt",
                "tool_name": "ask_user_question",
                "input": {"questions": []},
            },
        }
    )
    await collector.consume(
        {
            "method": "tools",
            "seq": 2,
            "timestamp": 1_777_000_123_789,
            "data": {
                "event": "tool-error",
                "tool_call_id": "call-interrupt",
                "message": "Interrupt",
            },
        }
    )

    assert observed[0]["error_message"] == "Interrupt"
    assert observed[0]["duration_ms"] == 200
    assert observed[0]["finished_sequence"] == 2


@pytest.mark.asyncio
async def test_collector_rejects_tool_start_without_object_input():
    collector = ToolMessageAuditCollector(
        run_id="run-1",
        request_id="request-1",
        thread_id="thread-1",
        worker_id="worker-1",
    )

    with pytest.raises(ValueError, match="input 必须是对象"):
        await collector.consume(
            {
                "method": "tools",
                "seq": 1,
                "timestamp": 1_777_000_123_456,
                "data": {
                    "event": "tool-started",
                    "tool_call_id": "call-1",
                    "tool_name": "search",
                    "input": "not-an-object",
                },
            }
        )
