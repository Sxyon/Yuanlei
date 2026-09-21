"""项目对话中 Agent 驱动 opencode/codex 两轮协作的真实 E2E。"""

from __future__ import annotations

import asyncio
import os
import uuid
from functools import partial

import asyncpg
import pytest

from e2e_helpers import postgres_dsn, wait_for_run
from test.live_api_cleanup import make_test_conversation_metadata, make_test_conversation_title
from yuxi.agents.backends.sandbox.provider import SandboxScope, get_sandbox_provider

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _provider() -> tuple[str, str]:
    provider = os.getenv("E2E_CODING_PROVIDER_ID")
    model = os.getenv("E2E_CODING_MODEL")
    if not provider or not model:
        pytest.skip("真实编码 E2E 需要 E2E_CODING_PROVIDER_ID 与 E2E_CODING_MODEL")
    return provider, model


async def _configure_credential(client, headers, *, executor: str, provider: str, model: str):
    response = await client.put(
        "/api/user/coding-credentials",
        headers=headers,
        json={
            "executor": executor,
            "source": "model_provider",
            "model_provider_id": provider,
            "key_mode": "inherit",
            "model": model,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["availability"] == "active"


async def _require_empty_test_credential_scope(client, headers) -> None:
    """真实 E2E 不覆盖测试账号已有凭据；有冲突时要求改用专用账号。"""
    response = await client.get("/api/user/coding-credentials", headers=headers)
    assert response.status_code == 200, response.text
    conflicts = [
        item
        for item in response.json()
        if item.get("executor") in {"opencode", "codex"} and item.get("availability") != "deleted"
    ]
    if conflicts:
        pytest.skip("真实编码 E2E 要求没有既有 opencode/codex 凭据的专用测试账号")


async def _create_project(client, headers) -> tuple[str, str]:
    name = f"pytest-coding-e2e-{uuid.uuid4().hex[:10]}"
    directory = await client.post("/api/workspace/directory", headers=headers, json={"parent_path": "/", "name": name})
    assert directory.status_code == 200, directory.text
    project = await client.post(
        "/api/projects",
        headers=headers,
        json={
            "request_id": f"pytest-coding-e2e-{uuid.uuid4()}",
            "name": name,
            "workdir": {"mode": "linked", "path": name},
        },
    )
    assert project.status_code == 200, project.text
    return str(project.json()["id"]), name


async def _create_agent(client, headers, *, project_id: str, provider: str, model: str) -> str:
    response = await client.post(
        f"/api/projects/{project_id}/agents",
        headers=headers,
        json={
            "name": f"pytest-coding-e2e-{uuid.uuid4().hex[:8]}",
            "backend_id": "ChatbotAgent",
            "config_json": {
                "context": {
                    "model": f"{provider}:{model}",
                    "system_prompt": (
                        "你是编码协作 E2E Agent。用户要求使用编码执行器时，必须实际调用指定的 "
                        "coding_session_start，再用返回的 session_id 调用 coding_session_send；不得自行创建文件。"
                        "总共只能调用两次编码工具：start 成功一次、send 成功一次。第二次返回后立即给出最终回答，"
                        "禁止调用 status、第三次 send 或重新 start。"
                    ),
                    "max_execution_steps": 20,
                },
                "sandbox": {
                    "mode": "dedicated",
                    "lifecycle": "persistent",
                    "resume_policy": "auto",
                    "idle_suspend_seconds": 1800,
                },
                "coding": {
                    "executors": ["opencode", "codex"],
                    "default_executor": "opencode",
                },
            },
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["slug"])


async def _run_executor(client, headers, *, slug: str, project_id: str, executor: str):
    thread = await client.post(
        "/api/chat/thread",
        headers=headers,
        json={
            "agent_id": slug,
            "project_id": project_id,
            "title": make_test_conversation_title(f"coding-{executor}"),
            "metadata": make_test_conversation_metadata(f"coding-{executor}", e2e=True),
        },
    )
    assert thread.status_code == 200, thread.text
    thread_id = str(thread.json()["id"])
    file_name = f"coding-{executor}-{uuid.uuid4().hex[:8]}.txt"
    query = (
        f"必须实际使用 executor={executor}。先调用 coding_session_start，plan_first=false、wait=true、max_turns=2，"
        f"让执行器在 Workdir 根目录创建 {file_name}，内容严格为 FIRST。然后使用同一 session_id 调用 "
        "coding_session_send，wait=true，只告诉它：继续上一轮原生会话，把上一轮创建的那个文件内容由 FIRST "
        "改成 SECOND，不得创建新文件，并自行读取核对结果。两次工具调用完成后立即停止，只报告 session_id。"
    )
    response = await client.post(
        "/api/agent/runs",
        headers=headers,
        json={
            "agent_slug": slug,
            "thread_id": thread_id,
            "query": query,
            "tool_approval_mode": "always_trust",
            "meta": {"request_id": f"pytest-coding-{executor}-{uuid.uuid4()}"},
        },
    )
    assert response.status_code == 200, response.text
    run_id = str(response.json()["run_id"])
    run = await wait_for_run(client, headers, run_id)

    conn = await asyncpg.connect(postgres_dsn())
    try:
        session = await conn.fetchrow(
            """
            SELECT cs.id, cs.conversation_id, cs.parent_run_id, cs.project_id, cs.executor,
                   cs.cli_session_ref,
                   cs.runtime_scope_id, ar.conversation_id AS run_conversation_id,
                   COALESCE(ars.scope_key, ar.runtime_scope_id) AS run_scope_id,
                   c.project_id AS conversation_project_id
              FROM coding_sessions cs
              JOIN agent_runs ar ON ar.id = cs.parent_run_id
              JOIN conversations c ON c.id = ar.conversation_id
              LEFT JOIN agent_run_scopes ars ON ars.run_id = ar.id
             WHERE cs.parent_run_id = $1 AND cs.executor = $2
            """,
            run_id,
            executor,
        )
        turns = await conn.fetch(
            """
            SELECT cst.seq, cst.status, cst.result_summary
              FROM coding_session_turns cst
             WHERE cst.session_id = $1
             ORDER BY cst.seq
            """,
            session["id"] if session else "",
        )
        session_refs = await conn.fetch(
            """
            SELECT cst.seq AS turn_seq, cse.payload_json ->> 'session_ref' AS session_ref
              FROM coding_session_events cse
              JOIN coding_session_turns cst ON cst.id = cse.turn_id
             WHERE cse.session_id = $1 AND cse.kind = 'session_ref'
             ORDER BY cse.seq
            """,
            session["id"] if session else "",
        )
        errors = await conn.fetch(
            """
            SELECT cse.kind, cse.payload_json
              FROM coding_session_events cse
              JOIN coding_sessions cs ON cs.id = cse.session_id
             WHERE cs.parent_run_id = $1 AND cse.kind IN ('error', 'session_status')
             ORDER BY cse.seq
            """,
            run_id,
        )
        assert run["status"] == "completed", {"run": run, "coding_events": [dict(row) for row in errors]}
        assert session is not None
        assert session["parent_run_id"] == run_id
        assert session["project_id"] == project_id
        assert session["conversation_project_id"] == project_id
        assert session["conversation_id"] == session["run_conversation_id"]
        assert session["runtime_scope_id"] == session["run_scope_id"]
        assert [(row["seq"], row["status"]) for row in turns] == [
            (1, "completed"),
            (2, "completed"),
        ]
        assert session["cli_session_ref"]
        refs_by_turn = {
            seq: {str(row["session_ref"] or "") for row in session_refs if row["turn_seq"] == seq} for seq in (1, 2)
        }
        assert refs_by_turn == {
            1: {session["cli_session_ref"]},
            2: {session["cli_session_ref"]},
        }
    finally:
        await conn.close()

    preview = await client.get("/api/workspace/file", headers=headers, params={"path": f"/{file_name}"})
    if preview.status_code == 404:
        preview = await client.get(
            "/api/workspace/file",
            headers=headers,
            params={"path": f"/{thread.json()['workdir_path']}/{file_name}"},
        )
    assert preview.status_code == 200, preview.text
    assert str(preview.json().get("content") or "").strip() == "SECOND", [dict(row) for row in turns]
    return thread_id


async def _release_project_sandboxes(project_id: str) -> None:
    """释放 E2E 创建的长驻 runtime，避免测试清理只删数据库不删容器。"""
    conn = await asyncpg.connect(postgres_dsn())
    try:
        rows = await conn.fetch(
            "SELECT scope_key, sandbox_id FROM agent_sandboxes WHERE project_id = $1",
            project_id,
        )
    finally:
        await conn.close()
    provider = get_sandbox_provider()
    inventory = {item.sandbox_id: item for item in await asyncio.to_thread(provider.list_sandboxes)}
    for row in rows:
        record = inventory.get(row["sandbox_id"])
        if record is None:
            continue
        await asyncio.to_thread(
            partial(
                provider.release_scope,
                SandboxScope.from_cache_key(row["scope_key"]),
                clear_cache_on_delete_failure=True,
                workdir_path=record.workdir_path,
            )
        )


async def test_agent_drives_opencode_and_codex_two_turns(e2e_client, e2e_headers):
    """两个真实执行器都由项目对话 Agent 完成两轮并写入 Project Workdir。"""
    provider, model = _provider()
    project_id = directory = slug = None
    thread_ids: list[str] = []
    configured_executors: list[str] = []
    try:
        executors = ("opencode", "codex")
        assert set(executors) == {"opencode", "codex"} and len(executors) == 2
        await _require_empty_test_credential_scope(e2e_client, e2e_headers)
        for executor in executors:
            await _configure_credential(e2e_client, e2e_headers, executor=executor, provider=provider, model=model)
            configured_executors.append(executor)
        project_id, directory = await _create_project(e2e_client, e2e_headers)
        slug = await _create_agent(
            e2e_client,
            e2e_headers,
            project_id=project_id,
            provider=provider,
            model=model,
        )
        for executor in executors:
            thread_ids.append(
                await _run_executor(
                    e2e_client,
                    e2e_headers,
                    slug=slug,
                    project_id=project_id,
                    executor=executor,
                )
            )
    finally:
        if project_id:
            await _release_project_sandboxes(project_id)
        for thread_id in thread_ids:
            await e2e_client.delete(f"/api/chat/thread/{thread_id}", headers=e2e_headers)
        if project_id:
            await e2e_client.delete(f"/api/projects/{project_id}", headers=e2e_headers)
        if directory:
            await e2e_client.delete("/api/workspace/file", headers=e2e_headers, params={"path": f"/{directory}"})
        if slug:
            await e2e_client.delete(f"/api/agent/{slug}", headers=e2e_headers)
        for executor in configured_executors:
            await e2e_client.delete(
                "/api/user/coding-credentials",
                headers=e2e_headers,
                params={"executor": executor, "provider": provider},
            )
