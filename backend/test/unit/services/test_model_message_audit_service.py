from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from yuxi.services import model_message_audit_service
from yuxi.services.model_message_audit_service import ModelMessageAuditCollector


class _FakeDb:
    pass


@pytest.mark.asyncio
async def test_collector_projects_real_v3_message_lifecycle(monkeypatch):
    """真实 v3 start/delta/finish 形状必须保留来源键、顺序、时间和 usage。"""
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

        async def finish(self, **kwargs):
            calls.append(("finish", kwargs))
            return SimpleNamespace(id=1)

    monotonic_values = iter([100.0, 100.321])
    monkeypatch.setattr(model_message_audit_service.pg_manager, "get_async_session_context", session_context)
    monkeypatch.setattr(model_message_audit_service, "ModelMessageAuditRepository", FakeRepository)
    monkeypatch.setattr(model_message_audit_service, "monotonic", lambda: next(monotonic_values))

    collector = ModelMessageAuditCollector(
        run_id="run-1",
        request_id="request-1",
        thread_id="thread-1",
        worker_id="worker-1",
    )
    metadata = {
        "run_id": "langchain-model-run-1",
        "stream_event": {
            "method": "messages",
            "namespace": ["model:abc"],
            "seq": 7,
            "timestamp": 1_777_000_123_456,
        },
    }
    await collector.consume(
        {
            "event": "message-start",
            "role": "ai",
            "id": "lc_run--model-message-1",
            "metadata": {"provider": "openai"},
        },
        metadata,
    )
    await collector.consume(
        {
            "event": "content-block-delta",
            "index": 0,
            "delta": {"type": "text-delta", "text": "hello"},
        },
        metadata,
    )
    await collector.consume(
        {
            "event": "content-block-finish",
            "index": 0,
            "content": {"type": "text", "text": "hello"},
        },
        metadata,
    )
    finish_metadata = {
        **metadata,
        "stream_event": {**metadata["stream_event"], "seq": 8, "timestamp": 1_777_000_123_789},
    }
    await collector.consume(
        {
            "event": "message-finish",
            "usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10},
            "metadata": {"model_name": "deterministic-chat"},
        },
        finish_metadata,
    )

    assert calls[0][0] == "start"
    assert calls[0][1]["operation_id"] == "lc_run--model-message-1"
    assert calls[0][1]["sequence"] == 7
    assert calls[0][1]["metadata"]["model_run_id"] == "langchain-model-run-1"
    assert calls[1] == (
        "finish",
        {
            "run_id": "run-1",
            "request_id": "request-1",
            "thread_id": "thread-1",
            "worker_id": "worker-1",
            "operation_id": "lc_run--model-message-1",
            "content": "hello",
            "finished_at": calls[1][1]["finished_at"],
            "duration_ms": 321,
            "usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10},
            "metadata": {
                "namespace": ["model:abc"],
                "content": [{"type": "text", "text": "hello"}],
                "tool_calls": [],
                "finished_sequence": 8,
                "finish_metadata": {"model_name": "deterministic-chat"},
            },
        },
    )


@pytest.mark.asyncio
async def test_collector_rejects_start_without_protocol_sequence():
    collector = ModelMessageAuditCollector(
        run_id="run-1",
        request_id="request-1",
        thread_id="thread-1",
        worker_id="worker-1",
    )

    with pytest.raises(ValueError, match="seq"):
        await collector.consume(
            {"event": "message-start", "role": "ai", "id": "message-1"},
            {"run_id": "model-run-1", "stream_event": {"timestamp": 1_777_000_123_456}},
        )


@pytest.mark.asyncio
async def test_duplicate_start_preserves_collected_content_and_monotonic_clock(monkeypatch):
    """同一 Model start 重放不得清空聚合内容或重置 monotonic 起点。"""
    db = _FakeDb()
    finishes: list[dict] = []
    created_values = iter([True, False])

    @asynccontextmanager
    async def session_context():
        yield db

    class FakeRepository:
        def __init__(self, _db):
            pass

        async def start(self, **_kwargs):
            return SimpleNamespace(id=1), next(created_values)

        async def finish(self, **kwargs):
            finishes.append(kwargs)
            return SimpleNamespace(id=1)

    monotonic_values = iter([100.0, 100.1, 100.4])
    monkeypatch.setattr(model_message_audit_service.pg_manager, "get_async_session_context", session_context)
    monkeypatch.setattr(model_message_audit_service, "ModelMessageAuditRepository", FakeRepository)
    monkeypatch.setattr(model_message_audit_service, "monotonic", lambda: next(monotonic_values))

    collector = ModelMessageAuditCollector(
        run_id="run-1",
        request_id="request-1",
        thread_id="thread-1",
        worker_id="worker-1",
    )
    metadata = {
        "run_id": "model-run-1",
        "stream_event": {"seq": 1, "timestamp": 1_777_000_123_456},
    }
    start = {"event": "message-start", "role": "ai", "id": "message-1"}
    await collector.consume(start, metadata)
    await collector.consume(
        {"event": "content-block-delta", "delta": {"type": "text-delta", "text": "before"}},
        metadata,
    )
    await collector.consume(start, metadata)
    await collector.consume(
        {"event": "content-block-delta", "delta": {"type": "text-delta", "text": " after"}},
        metadata,
    )
    await collector.consume(
        {"event": "message-finish", "usage": {}},
        {"run_id": "model-run-1", "stream_event": {"seq": 2, "timestamp": 1_777_000_123_789}},
    )

    assert finishes[0]["content"] == "before after"
    assert finishes[0]["duration_ms"] == 400


@pytest.mark.asyncio
async def test_active_lifecycle_rejects_replacement_operation_id(monkeypatch):
    """同一 lifecycle key 不得用新 operation id 覆盖进程内状态。"""
    db = _FakeDb()

    @asynccontextmanager
    async def session_context():
        yield db

    class FakeRepository:
        def __init__(self, _db):
            pass

        async def start(self, **_kwargs):
            return SimpleNamespace(id=1), True

    monkeypatch.setattr(model_message_audit_service.pg_manager, "get_async_session_context", session_context)
    monkeypatch.setattr(model_message_audit_service, "ModelMessageAuditRepository", FakeRepository)

    collector = ModelMessageAuditCollector(
        run_id="run-1",
        request_id="request-1",
        thread_id="thread-1",
        worker_id="worker-1",
    )
    metadata = {
        "run_id": "model-run-1",
        "stream_event": {"seq": 1, "timestamp": 1_777_000_123_456},
    }
    await collector.consume({"event": "message-start", "role": "ai", "id": "message-1"}, metadata)

    with pytest.raises(ValueError, match="operation id"):
        await collector.consume({"event": "message-start", "role": "ai", "id": "message-2"}, metadata)
