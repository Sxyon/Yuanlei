"""显式选用真实模型，核对 API→worker→SSE→PostgreSQL→历史的推理一致性。"""

import json
import os
from uuid import uuid4

import asyncpg
import pytest
from e2e_helpers import cancel_run, delete_agent, iter_sse, postgres_dsn, wait_for_run

from test.live_api_cleanup import make_test_conversation_metadata, make_test_conversation_title

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.slow]


async def test_reasoning_stream_matches_persisted_history(e2e_client, e2e_headers, e2e_agent_context):
    """无工具的单次编码问答完成后，SSE 原文必须等于同一 Run 的持久化推理。"""
    spec = os.getenv("YUXI_REASONING_E2E_MODEL")
    if not spec:
        pytest.skip("显式配置 YUXI_REASONING_E2E_MODEL 后才调用真实模型")
    client, headers = e2e_client, e2e_headers
    slug = f"e2e-async-agent-reasoning-{uuid4().hex[:8]}"
    response = await client.post(
        "/api/agent",
        headers=headers,
        json={
            "name": "E2E 推理展示测试",
            "slug": slug,
            "backend_id": "ChatbotAgent",
            "config_json": {
                "context": {
                    "model": spec,
                    "system_prompt": "You review Python code. Answer concisely. Do not use tools.",
                    "tools": [],
                    "knowledges": [],
                    "mcps": [],
                    "skills": [],
                    "subagents": [],
                }
            },
            "share_config": {
                "version": 2,
                "read_scope": {
                    "access_level": "user",
                    "department_ids": [],
                    "user_uids": [e2e_agent_context["uid"]],
                },
                "manage_scope": None,
            },
        },
    )
    assert response.status_code == 200
    thread_id = run_id = None
    completed = False
    try:
        response = await client.post(
            "/api/chat/thread",
            headers=headers,
            json={
                "agent_id": slug,
                "title": make_test_conversation_title("reasoning-e2e"),
                "metadata": make_test_conversation_metadata("reasoning-e2e", e2e=True),
            },
        )
        assert response.status_code == 200
        thread_id = response.json().get("thread_id") or response.json().get("id")
        response = await client.post(
            "/api/agent/runs",
            headers=headers,
            json={
                "agent_slug": slug,
                "thread_id": thread_id,
                "query": (
                    "Review def double(x): return x + 1. Is it correct for doubling all integers? "
                    "Give a counterexample and the corrected return statement."
                ),
                "meta": {"request_id": f"reasoning-e2e-{uuid4()}"},
            },
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]
        reasoning_parts = []
        async for event, envelope in iter_sse(client, headers, run_id):
            payload = envelope.get("payload") or {}
            chunks = payload.get("items") or [payload.get("chunk") or {}]
            for chunk in chunks:
                semantic = chunk.get("stream_event") or {}
                if semantic.get("type") == "message_delta":
                    reasoning_parts.append(semantic.get("reasoning_content") or "")
            if event == "end":
                break
        run = await wait_for_run(client, headers, run_id)
        assert run["status"] == "completed", run.get("error_type")
        completed = True
        reasoning = "".join(reasoning_parts)
        history = await client.get(f"/api/chat/thread/{thread_id}/history", headers=headers)
        assert history.status_code == 200
        messages = [m for m in history.json()["history"] if m["type"] == "ai" and m["run_id"] == run_id]
        assert len(messages) == 1
        assert messages[0]["reasoning_content"] == reasoning
        assert messages[0]["content"].strip()
        conn = await asyncpg.connect(postgres_dsn())
        try:
            row = await conn.fetchrow(
                "SELECT content, extra_metadata FROM messages WHERE id=$1 AND run_id=$2", messages[0]["id"], run_id
            )
            metadata = (
                json.loads(row["extra_metadata"]) if isinstance(row["extra_metadata"], str) else row["extra_metadata"]
            )
            blocks = metadata["content"]
            assert isinstance(blocks, list)
            assert "".join(b["reasoning"] for b in blocks if b["type"] == "reasoning") == reasoning
            assert "reasoning_content" not in (metadata.get("additional_kwargs") or {})
            assert row["content"] == messages[0]["content"]
        finally:
            await conn.close()
        print(json.dumps({"model": spec, "sse_history_pg_equal": True, "reasoning_chars": len(reasoning)}))
    finally:
        if run_id and not completed:
            await cancel_run(client, headers, run_id)
        if thread_id:
            response = await client.delete(f"/api/chat/thread/{thread_id}", headers=headers)
            assert response.status_code == 200
        await delete_agent(client, headers, slug)
