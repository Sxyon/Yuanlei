from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import suppress

import asyncpg
import pytest
from yuxi.services.run_queue_service import append_run_stream_event, get_redis_client
from yuxi.storage.redis import close_async_redis_client

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def isolated_run_events_redis_client():
    """确保共享 Redis 客户端只在当前测试的事件循环内使用。"""
    await close_async_redis_client()
    yield
    await close_async_redis_client()


async def test_stream_batch_preserves_payload_and_expiry():
    """从真实 Redis 回读批量发布后的事件标识、内容和 TTL。"""
    from yuxi.services.run_queue_service import RUN_EVENTS_STREAM_TTL_SECONDS

    run_id = str(uuid.uuid4())
    key = f"run:events:{run_id}"
    redis = await get_redis_client()
    try:
        seq = await append_run_stream_event(run_id, "metadata", {"probe": "batch"}, thread_id="test-thread")
        rows = await redis.xrange(key)
        assert len(rows) == 1
        assert rows[0][0] == seq
        payload = json.loads(rows[0][1]["payload"])
        assert payload["run_id"] == run_id
        assert payload["thread_id"] == "test-thread"
        assert payload["payload"] == {"probe": "batch"}
        assert 0 < await redis.ttl(key) <= RUN_EVENTS_STREAM_TTL_SECONDS
    finally:
        await redis.delete(key)


def _postgres_dsn() -> str:
    return os.getenv("POSTGRES_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/yuxi").replace(
        "+asyncpg", ""
    )


async def _collect_sse_payloads(
    response,
    *,
    first_event_received: asyncio.Event | None = None,
) -> list[tuple[str, dict, str | None]]:
    event = "message"
    event_id = None
    data_lines: list[str] = []
    payloads: list[tuple[str, dict, str | None]] = []

    async for line in response.aiter_lines():
        if not line:
            if data_lines:
                payloads.append((event, json.loads("\n".join(data_lines)), event_id))
                if first_event_received is not None and len(payloads) == 1:
                    first_event_received.set()
                if event == "end":
                    return payloads
            event = "message"
            event_id = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip() or "message"
        elif line.startswith("id:"):
            event_id = line.removeprefix("id:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())

    return payloads


async def test_run_events_verbose_false_returns_compact_payload(test_client, standard_user):
    uid = str(standard_user["user"]["uid"])
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    request_id = f"req-{uuid.uuid4()}"

    conn = await asyncpg.connect(_postgres_dsn())
    try:
        await conn.execute(
            """
            INSERT INTO agent_runs
                (
                    id, conversation_thread_id, runtime_scope_id, agent_slug, uid, request_id,
                    input_payload, token_usage, status, run_type, source, channel, origin_metadata
                )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, '{}'::jsonb, $8, $9, 'chat', 'web', '{}'::jsonb)
            """,
            run_id,
            thread_id,
            thread_id,
            "deep-research",
            uid,
            request_id,
            json.dumps({"query": "写一个冒泡排序"}, ensure_ascii=False),
            "completed",
            "chat",
        )
    finally:
        await conn.close()

    try:
        await append_run_stream_event(
            run_id,
            "metadata",
            {
                "request_id": request_id,
                "agent_slug": "deep-research",
                "backend_id": "ChatbotAgent",
                "uid": uid,
                "run_type": "chat",
                "source": "chat",
            },
            thread_id=thread_id,
        )
        await append_run_stream_event(
            run_id,
            "custom",
            {
                "name": "yuxi.agent_state",
                "chunk": {
                    "request_id": request_id,
                    "response": None,
                    "thread_id": thread_id,
                    "status": "agent_state",
                    "agent_state": {
                        "todos": [],
                        "files": {},
                        "artifacts": [],
                        "subagent_runs": [],
                    },
                    "meta": {"uid": uid},
                },
                "agent_state": {
                    "todos": [],
                    "files": {},
                    "artifacts": [],
                    "subagent_runs": [],
                },
            },
            thread_id=thread_id,
        )
        await append_run_stream_event(
            run_id,
            "messages",
            {
                "items": [
                    {
                        "request_id": request_id,
                        "response": "你",
                        "thread_id": thread_id,
                        "status": "loading",
                        "stream_event": {
                            "type": "tool_call",
                            "message_id": "msg-1",
                            "tool_call_id": "call-1",
                            "name": "ls",
                            "args": {"path": "/home/gem/user-data/outputs"},
                            "thread_id": thread_id,
                            "namespace": [],
                        },
                        "metadata": {
                            "langfuse_user_id": uid,
                            "langgraph_checkpoint_ns": "model:checkpoint",
                        },
                    }
                ]
            },
            thread_id=thread_id,
        )
        await append_run_stream_event(
            run_id,
            "end",
            {"status": "completed", "chunk": {"status": "finished", "request_id": request_id, "meta": {"uid": uid}}},
            thread_id=thread_id,
        )

        async with test_client.stream(
            "GET",
            f"/api/agent/runs/{run_id}/events",
            params={"verbose": "false"},
            headers=standard_user["headers"],
        ) as response:
            assert response.status_code == 200, response.text
            payloads = await _collect_sse_payloads(response)

        assert {event for event, _payload, _event_id in payloads} == {"metadata", "messages", "end"}

        metadata_event = next(item for item in payloads if item[0] == "metadata")
        assert metadata_event[1]["payload"] == {"run_type": "chat", "source": "chat"}

        message_event = next(item for item in payloads if item[0] == "messages")
        message_chunk = message_event[1]["payload"]["items"][0]
        assert message_event[1]["request_id"] == request_id
        assert message_event[2]
        assert "request_id" not in message_chunk
        assert "metadata" not in message_chunk
        assert "response" not in message_chunk
        assert "thread_id" not in message_chunk
        assert message_chunk["stream_event"]["tool_call_id"] == "call-1"
        assert "thread_id" not in message_chunk["stream_event"]
        assert "namespace" not in message_chunk["stream_event"]

        end_event = next(item for item in payloads if item[0] == "end")
        assert end_event[1]["request_id"] == request_id
        assert end_event[1]["payload"]["status"] == "completed"
        assert "request_id" not in end_event[1]["payload"]["chunk"]
        assert "meta" not in end_event[1]["payload"]["chunk"]
    finally:
        redis = await get_redis_client()
        await redis.delete(f"run:events:{run_id}")
        conn = await asyncpg.connect(_postgres_dsn())
        try:
            await conn.execute("DELETE FROM agent_runs WHERE id = $1", run_id)
        finally:
            await conn.close()


async def test_run_events_delivers_new_redis_event_without_one_second_poll_delay(
    test_client,
    standard_user,
    admin_headers,
):
    uid = str(standard_user["user"]["uid"])
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    request_id = f"req-{uuid.uuid4()}"

    conn = await asyncpg.connect(_postgres_dsn())
    try:
        await conn.execute(
            """
            INSERT INTO agent_runs
                (
                    id, conversation_thread_id, runtime_scope_id, agent_slug, uid, request_id,
                    input_payload, token_usage, status, run_type, source, channel, origin_metadata
                )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, '{}'::jsonb, $8, $9, 'chat', 'web', '{}'::jsonb)
            """,
            run_id,
            thread_id,
            thread_id,
            "deep-research",
            uid,
            request_id,
            json.dumps({"query": "SSE latency probe"}),
            "running",
            "chat",
        )
    finally:
        await conn.close()

    await append_run_stream_event(
        run_id,
        "messages",
        {"items": [{"status": "loading", "response": "probe-ready"}]},
        thread_id=thread_id,
    )
    first_event_received = asyncio.Event()
    published_at = None

    async def publish_terminal_event():
        nonlocal published_at
        await first_event_received.wait()
        await asyncio.sleep(0.15)
        await append_run_stream_event(
            run_id,
            "end",
            {"status": "completed", "request_id": request_id},
            thread_id=thread_id,
        )
        published_at = asyncio.get_running_loop().time()

    publisher = asyncio.create_task(publish_terminal_event())
    try:
        async with test_client.stream(
            "GET",
            f"/api/agent/runs/{run_id}/events",
            params={"verbose": "false"},
            headers=standard_user["headers"],
        ) as response:
            assert response.status_code == 200, response.text
            payloads = await _collect_sse_payloads(response, first_event_received=first_event_received)

        assert published_at is not None
        elapsed_after_publish = asyncio.get_running_loop().time() - published_at
        assert elapsed_after_publish < 0.6
        assert [event for event, _payload, _event_id in payloads] == ["messages", "end"]
        assert payloads[-1][1]["payload"]["status"] == "completed"

        async with test_client.stream(
            "GET",
            f"/api/agent/runs/{run_id}/events",
            params={"verbose": "false"},
            headers=admin_headers,
        ) as response:
            assert response.status_code == 200, response.text
            unauthorized_payloads = await _collect_sse_payloads(response)

        assert [event for event, _payload, _event_id in unauthorized_payloads] == ["error"]
        assert unauthorized_payloads[0][1]["message"] == "运行任务不存在"
    finally:
        if not publisher.done():
            publisher.cancel()
            with suppress(asyncio.CancelledError):
                await publisher
        else:
            await publisher
        redis = await get_redis_client()
        await redis.delete(f"run:events:{run_id}")
        conn = await asyncpg.connect(_postgres_dsn())
        try:
            await conn.execute("DELETE FROM agent_runs WHERE id = $1", run_id)
        finally:
            await conn.close()
