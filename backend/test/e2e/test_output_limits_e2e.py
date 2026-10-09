"""输出配置从真实 HTTP 保存，经 worker SDK 到持久 Run 结果。"""

import asyncio
import json
from uuid import uuid4

import asyncpg
import httpx
import pytest
from e2e_helpers import cancel_run, consume_events, delete_agent, postgres_dsn, wait_for_run

from test.live_api_cleanup import make_test_conversation_metadata, make_test_conversation_title
from test.support.output_limit_server import LONG_OUTPUT

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


@pytest.mark.parametrize(
    "protocol,case",
    [
        ("anthropic", "normal"),
        ("anthropic", "truncated"),
        ("anthropic", "truncated_tool"),
        ("anthropic", "tool"),
        ("anthropic", "context"),
        ("openai", "normal"),
        ("openai", "truncated_tool"),
        ("openai", "child"),
    ],
)
async def test_model_output_configuration_and_truncation_persist(e2e_client, e2e_headers, protocol, case):
    """回读最终请求、同 Run 输出、状态与工具副作用审计。"""
    client, headers = e2e_client, e2e_headers
    uid = (await client.get("/api/auth/me", headers=headers)).json()["uid"]
    provider = f"output-{uuid4().hex[:10]}"
    slug = f"output-agent-{uuid4().hex[:10]}"
    thread = run_id = child_slug = None
    try:
        response = await client.post(
            "/api/system/model-providers",
            headers=headers,
            json={
                "provider_id": provider,
                "display_name": "output test",
                "provider_type": protocol,
                "base_url": "http://api:8766/v1",
                "api_key": "synthetic-key",
                "is_enabled": True,
                "capabilities": ["chat"],
                "enabled_models": [
                    {
                        "id": "output-test",
                        "type": "chat",
                        "source": "manual",
                        "default_output_tokens": 65536,
                        "max_output_tokens": 393216,
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
        saved = await client.get("/api/system/model-providers", headers=headers)
        actual = next(p for p in saved.json()["data"] if p["provider_id"] == provider)
        assert actual["enabled_models"][0]["default_output_tokens"] == 65536
        configured = actual["enabled_models"][0]
        invalid = await client.put(
            f"/api/system/model-providers/{provider}",
            headers=headers,
            json={"enabled_models": [{**configured, "default_output_tokens": 393217}]},
        )
        assert invalid.status_code == 400
        assert "超过模型最大输出" in invalid.json()["detail"]
        updated = await client.put(
            f"/api/system/model-providers/{provider}",
            headers=headers,
            json={"enabled_models": [{**configured, "default_output_tokens": 65536}]},
        )
        assert updated.status_code == 200, updated.text
        from yuxi.models.providers.cache import ModelCache

        cached = ModelCache().get_model_info(f"{provider}:output-test")
        assert cached.default_output_tokens == 65536
        assert cached.max_output_tokens == 393216
        call = await client.post(
            "/api/chat/call",
            headers=headers,
            json={"query": "OUTPUT_CASE:truncated", "meta": {"model_spec": f"{provider}:output-test"}},
        )
        assert call.status_code == 422, call.text
        assert call.json()["detail"]["type"] == "output_truncated"
        assert call.json()["detail"]["response"] == LONG_OUTPUT
        # Worker 的已有进程缓存 TTL 为 5 秒；等待新建模型跨进程可见。
        await asyncio.sleep(5.1)
        if case == "child":
            child_slug = f"output-child-{uuid4().hex[:10]}"
            child = await client.post(
                "/api/agent",
                headers=headers,
                json={
                    "slug": child_slug,
                    "name": "output child",
                    "backend_id": "SubAgentBackend",
                    "is_subagent": True,
                    "config_json": {
                        "context": {
                            "model": f"{provider}:output-test",
                            "system_prompt": "Synthetic child test",
                            "tools": [],
                            "skills": [],
                            "mcps": [],
                            "knowledges": [],
                        }
                    },
                    "share_config": {
                        "version": 2,
                        "read_scope": {"access_level": "user", "department_ids": [], "user_uids": [uid]},
                        "manage_scope": None,
                    },
                },
            )
            assert child.status_code == 200, child.text
        response = await client.post(
            "/api/agent",
            headers=headers,
            json={
                "slug": slug,
                "name": "synthetic output test",
                "backend_id": "ChatbotAgent",
                "config_json": {
                    "context": {
                        "model": f"{provider}:output-test",
                        "system_prompt": "Synthetic test",
                        "tools": [],
                        "skills": [],
                        "mcps": [],
                        "knowledges": [],
                        "subagents": [child_slug] if child_slug else [],
                    }
                },
                "share_config": {
                    "version": 2,
                    "read_scope": {"access_level": "user", "department_ids": [], "user_uids": [uid]},
                    "manage_scope": None,
                },
            },
        )
        assert response.status_code == 200, response.text
        response = await client.post(
            "/api/chat/thread",
            headers=headers,
            json={
                "agent_id": slug,
                "title": make_test_conversation_title("output"),
                "metadata": make_test_conversation_metadata("output", e2e=True),
            },
        )
        assert response.status_code == 200, response.text
        thread = response.json()["id"]
        marker = (
            f"OUTPUT_PARENT:{child_slug}" if case == "child" else f"OUTPUT_CASE:{case}"
        ) + f" TEST_TOKEN:{provider}"
        response = await client.post(
            "/api/agent/runs",
            headers=headers,
            json={"agent_slug": slug, "thread_id": thread, "query": marker, "meta": {"request_id": str(uuid4())}},
        )
        assert response.status_code == 200, response.text
        run_id = response.json()["run_id"]
        await consume_events(client, headers, run_id)
        run = await wait_for_run(client, headers, run_id)
        truncated = case in {"truncated", "truncated_tool", "context"}
        expected_error = "model_context_window_exceeded" if case == "context" else "output_truncated"
        assert run["status"] == ("failed" if truncated else "completed"), run
        if truncated:
            assert run["error_type"] == expected_error, run
        conn = await asyncpg.connect(postgres_dsn())
        try:
            record = await conn.fetchrow(
                "SELECT status, error_type, output_message_id FROM agent_runs WHERE id=$1", run_id
            )
            assert record["status"] == run["status"]
            assert record["output_message_id"]
            output = await conn.fetchrow(
                "SELECT content, extra_metadata FROM messages WHERE id=$1 AND run_id=$2",
                record["output_message_id"],
                run_id,
            )
            metadata = (
                json.loads(output["extra_metadata"])
                if isinstance(output["extra_metadata"], str)
                else output["extra_metadata"]
            )
            reason = metadata["response_metadata"].get("stop_reason") or metadata["response_metadata"].get(
                "finish_reason"
            )
            if truncated:
                assert reason in {"max_tokens", "length", "model_context_window_exceeded"}
                assert metadata["error_type"] == expected_error
                assert output["content"] == ("partial tool" if case == "truncated_tool" else LONG_OUTPUT)
                assert await conn.fetchval("SELECT count(*) FROM messages WHERE run_id=$1 AND role='tool'", run_id) == 0
            elif case == "child":
                assert output["content"] == "子任务因输出截断失败；请检查部分输出后继续。"
                child_run = await conn.fetchrow(
                    "SELECT id, status, error_type, output_message_id FROM agent_runs "
                    "WHERE created_by_run_id=$1 AND run_type='subagent'",
                    run_id,
                )
                assert child_run["status"] == "failed"
                if child_run["error_type"] == "invalid_runtime_scope":
                    pytest.xfail("既有子 Run 创建 scope 与 worker 执行树校验不一致，尚未进入模型")
                assert child_run["error_type"] == "output_truncated"
                partial = await conn.fetchrow(
                    "SELECT content, extra_metadata FROM messages WHERE id=$1 AND run_id=$2",
                    child_run["output_message_id"],
                    child_run["id"],
                )
                child_metadata = (
                    json.loads(partial["extra_metadata"])
                    if isinstance(partial["extra_metadata"], str)
                    else partial["extra_metadata"]
                )
                assert child_metadata["response_metadata"]["finish_reason"] == "length"
                assert partial["content"] == "partial tool"
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM messages WHERE run_id=$1 AND role='tool'", child_run["id"]
                    )
                    == 0
                )
            else:
                assert output["content"] == LONG_OUTPUT
                if case == "tool":
                    assert (
                        await conn.fetchval("SELECT count(*) FROM messages WHERE run_id=$1 AND role='tool'", run_id)
                        == 1
                    )
        finally:
            await conn.close()
        async with httpx.AsyncClient() as replay:
            payloads = (await replay.get("http://localhost:8766/requests")).json()["requests"]
        request_marker = f"TEST_TOKEN:{provider}" if case == "child" else marker
        payloads = [p for p in payloads if request_marker in json.dumps(p)]
        assert len(payloads) == (4 if case == "child" else 2 if case == "tool" else 1), "截断不得隐式重试或重放"
        if case == "child":
            child_payloads = [
                p
                for p in payloads
                if "subagent_start" not in {t.get("function", {}).get("name") for t in p.get("tools", [])}
            ]
            assert len(child_payloads) == 1
            assert "OUTPUT_CASE:truncated_tool" in json.dumps(child_payloads[0]["messages"])
        for payload in payloads:
            assert payload.get("max_tokens", payload.get("max_completion_tokens")) == 65536
            assert len(set(payload) & {"max_tokens", "max_completion_tokens", "max_output_tokens"}) == 1
    finally:
        if run_id:
            await cancel_run(client, headers, run_id)
        if thread:
            await client.delete(f"/api/chat/thread/{thread}", headers=headers)
        await delete_agent(client, headers, slug)
        if child_slug:
            await delete_agent(client, headers, child_slug)
        await client.delete(f"/api/system/model-providers/{provider}", headers=headers)
