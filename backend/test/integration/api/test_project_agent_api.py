"""项目数字员工（ProjectAgent）真实 API 与 PostgreSQL 集成测试。"""

from __future__ import annotations

import uuid

import pytest
from test.live_api_cleanup import (
    make_test_conversation_metadata,
    make_test_conversation_title,
    make_test_resource_id,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _create_project(test_client, headers, label: str) -> tuple[str, str]:
    """创建 linked Project，返回 (project_id, workspace directory)。"""
    directory = f"pytest-project-agent-{label}-{uuid.uuid4().hex[:10]}"
    created = await test_client.post(
        "/api/workspace/directory",
        headers=headers,
        json={"parent_path": "/", "name": directory},
    )
    assert created.status_code == 200, created.text
    response = await test_client.post(
        "/api/projects",
        headers=headers,
        json={
            "request_id": make_test_resource_id(f"project-agent-{label}"),
            "name": f"pytest-project-agent-{label}",
            "workdir": {"mode": "linked", "path": directory},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"], directory


async def _delete_project(test_client, headers, project_id: str, directory: str) -> None:
    response = await test_client.delete(f"/api/projects/{project_id}", headers=headers)
    assert response.status_code in {200, 404}, response.text
    removed = await test_client.request(
        "DELETE",
        "/api/workspace/file",
        headers=headers,
        params={"path": directory},
    )
    assert removed.status_code in {200, 404}, removed.text


async def _delete_thread(test_client, headers, thread_id: str) -> None:
    response = await test_client.delete(f"/api/chat/thread/{thread_id}", headers=headers)
    assert response.status_code in {200, 404}, response.text


async def _delete_agent(test_client, headers, slug: str) -> None:
    response = await test_client.delete(f"/api/agent/{slug}", headers=headers)
    assert response.status_code in {200, 404}, response.text


async def _global_agent_slugs(test_client, headers, *, project_id: str | None = None) -> set[str]:
    params = {"project_id": project_id} if project_id else None
    response = await test_client.get("/api/agent", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return {item["slug"] for item in response.json()["agents"]}


def _agent_name(label: str) -> str:
    return f"pytest-project-agent-{label}-{uuid.uuid4().hex[:8]}"


async def _create_project_agent(test_client, headers, project_id: str, *, name: str, config_json: dict | None = None) -> dict:
    response = await test_client.post(
        f"/api/projects/{project_id}/agents",
        headers=headers,
        json={
            "name": name,
            "backend_id": "ChatbotAgent",
            "config_json": config_json
            or {"context": {"system_prompt": "项目专属人格", "max_execution_steps": 42}},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_project_agent_lifecycle_keeps_agent_out_of_global_lists(test_client, admin_headers):
    """项目数字员工只出现在项目上下文；覆盖层生效；项目删除后解绑回到个人列表。"""
    project_id, directory = await _create_project(test_client, admin_headers, "lifecycle")
    agent = await _create_project_agent(test_client, admin_headers, project_id, name=_agent_name("lifecycle"))
    slug = agent["slug"]
    try:
        assert agent["effective_context"]["system_prompt"] == "项目专属人格"
        assert agent["effective_context"]["max_execution_steps"] == 42
        assert agent["config_overrides"]["context"]["system_prompt"] == "项目专属人格"
        assert agent["config_json"] == {"context": {}}

        assert slug not in await _global_agent_slugs(test_client, admin_headers)
        assert slug in await _global_agent_slugs(test_client, admin_headers, project_id=project_id)

        listed = await test_client.get(f"/api/projects/{project_id}/agents", headers=admin_headers)
        assert listed.status_code == 200, listed.text
        assert slug in {item["slug"] for item in listed.json()["agents"]}

        project_listing = await test_client.get(
            "/api/agent",
            headers=admin_headers,
            params={"project_id": project_id},
        )
        assert project_listing.status_code == 200, project_listing.text
        bound_item = next(
            item for item in project_listing.json()["agents"] if item["slug"] == slug
        )
        assert bound_item["is_project_agent"] is True
        assert all(
            item.get("is_project_agent") is False
            for item in project_listing.json()["agents"]
            if item["slug"] != slug
        )

        detail = await test_client.get(
            f"/api/agent/{slug}",
            headers=admin_headers,
            params={"project_id": project_id},
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["agent"]["is_project_agent"] is True

        updated = await test_client.put(
            f"/api/projects/{project_id}/agents/{slug}",
            headers=admin_headers,
            json={"config_json": {"context": {"system_prompt": "更新后人格"}}},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["effective_context"]["system_prompt"] == "更新后人格"

        reset = await test_client.put(
            f"/api/projects/{project_id}/agents/{slug}",
            headers=admin_headers,
            json={"config_json": {}, "reset_fields": ["system_prompt"]},
        )
        assert reset.status_code == 200, reset.text
        assert "system_prompt" not in reset.json()["config_overrides"].get("context", {})
        assert reset.json()["effective_context"].get("system_prompt") is None
        assert reset.json()["effective_context"]["max_execution_steps"] == 42

        await _delete_project(test_client, admin_headers, project_id, directory)
        assert slug in await _global_agent_slugs(test_client, admin_headers)
    finally:
        await _delete_project(test_client, admin_headers, project_id, directory)
        await _delete_agent(test_client, admin_headers, slug)


async def test_bound_agent_is_rejected_outside_its_project_at_thread_and_run_boundaries(test_client, admin_headers):
    """绑定项目范围在提交边界 fail-closed，解绑后恢复全局行为。"""
    project_a, directory_a = await _create_project(test_client, admin_headers, "scope-a")
    project_b, directory_b = await _create_project(test_client, admin_headers, "scope-b")
    created = await test_client.post(
        "/api/agent",
        headers=admin_headers,
        json={
            "name": _agent_name("scope"),
            "backend_id": "ChatbotAgent",
            "config_json": {"context": {"system_prompt": "先全局后绑定"}},
        },
    )
    assert created.status_code == 200, created.text
    slug = created.json()["agent"]["slug"]
    thread_ids: list[str] = []
    try:
        bound_thread = await test_client.post(
            "/api/chat/thread",
            headers=admin_headers,
            json={
                "agent_id": slug,
                "project_id": project_b,
                "title": make_test_conversation_title("project-agent-scope-bound"),
                "metadata": make_test_conversation_metadata("project-agent-scope-bound"),
            },
        )
        assert bound_thread.status_code == 200, bound_thread.text
        thread_ids.append(bound_thread.json()["id"])

        bind = await test_client.post(
            f"/api/projects/{project_a}/agents/bind",
            headers=admin_headers,
            json={"agent_slug": slug},
        )
        assert bind.status_code == 200, bind.text

        run = await test_client.post(
            "/api/agent/runs",
            headers=admin_headers,
            json={
                "agent_slug": slug,
                "thread_id": thread_ids[0],
                "query": "hello",
                "meta": {"request_id": make_test_resource_id("project-agent-run")},
            },
        )
        assert run.status_code == 403, run.text

        other_project_thread = await test_client.post(
            "/api/chat/thread",
            headers=admin_headers,
            json={
                "agent_id": slug,
                "project_id": project_b,
                "title": make_test_conversation_title("project-agent-scope-other"),
                "metadata": make_test_conversation_metadata("project-agent-scope-other"),
            },
        )
        assert other_project_thread.status_code == 403, other_project_thread.text

        implicit_thread = await test_client.post(
            "/api/chat/thread",
            headers=admin_headers,
            json={
                "agent_id": slug,
                "title": make_test_conversation_title("project-agent-scope-implicit"),
                "metadata": make_test_conversation_metadata("project-agent-scope-implicit"),
            },
        )
        assert implicit_thread.status_code == 403, implicit_thread.text

        own_project_thread = await test_client.post(
            "/api/chat/thread",
            headers=admin_headers,
            json={
                "agent_id": slug,
                "project_id": project_a,
                "title": make_test_conversation_title("project-agent-scope-own"),
                "metadata": make_test_conversation_metadata("project-agent-scope-own"),
            },
        )
        assert own_project_thread.status_code == 200, own_project_thread.text
        thread_ids.append(own_project_thread.json()["id"])

        unbind = await test_client.delete(f"/api/projects/{project_a}/agents/{slug}", headers=admin_headers)
        assert unbind.status_code == 200, unbind.text
        assert unbind.json()["deleted_agent"] is False

        restored_thread = await test_client.post(
            "/api/chat/thread",
            headers=admin_headers,
            json={
                "agent_id": slug,
                "project_id": project_b,
                "title": make_test_conversation_title("project-agent-scope-restored"),
                "metadata": make_test_conversation_metadata("project-agent-scope-restored"),
            },
        )
        assert restored_thread.status_code == 200, restored_thread.text
        thread_ids.append(restored_thread.json()["id"])

        rebind = await test_client.post(
            f"/api/projects/{project_a}/agents/bind",
            headers=admin_headers,
            json={"agent_slug": slug},
        )
        assert rebind.status_code == 200, rebind.text
        deleted = await test_client.delete(
            f"/api/projects/{project_a}/agents/{slug}",
            headers=admin_headers,
            params={"delete_agent": "true"},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_agent"] is True
        gone = await test_client.get(f"/api/agent/{slug}", headers=admin_headers)
        assert gone.status_code == 404, gone.text
    finally:
        for thread_id in thread_ids:
            await _delete_thread(test_client, admin_headers, thread_id)
        await _delete_project(test_client, admin_headers, project_a, directory_a)
        await _delete_project(test_client, admin_headers, project_b, directory_b)
        await _delete_agent(test_client, admin_headers, slug)


async def test_bound_agent_rejects_context_compression_outside_project(test_client, admin_headers):
    """主动上下文压缩同样受项目范围约束，不能借维护动作绕过运行边界。"""
    project_a, directory_a = await _create_project(test_client, admin_headers, "compress-a")
    project_b, directory_b = await _create_project(test_client, admin_headers, "compress-b")
    created = await test_client.post(
        "/api/agent",
        headers=admin_headers,
        json={
            "name": _agent_name("compress"),
            "backend_id": "ChatbotAgent",
            "config_json": {"context": {}},
        },
    )
    assert created.status_code == 200, created.text
    slug = created.json()["agent"]["slug"]
    thread_id: str | None = None
    try:
        thread = await test_client.post(
            "/api/chat/thread",
            headers=admin_headers,
            json={
                "agent_id": slug,
                "project_id": project_b,
                "title": make_test_conversation_title("project-agent-compress"),
                "metadata": make_test_conversation_metadata("project-agent-compress"),
            },
        )
        assert thread.status_code == 200, thread.text
        thread_id = thread.json()["id"]

        bind = await test_client.post(
            f"/api/projects/{project_a}/agents/bind",
            headers=admin_headers,
            json={"agent_slug": slug},
        )
        assert bind.status_code == 200, bind.text

        compress = await test_client.post(
            f"/api/chat/thread/{thread_id}/compress",
            headers=admin_headers,
            json={},
        )
        assert compress.status_code == 403, compress.text
    finally:
        if thread_id:
            await _delete_thread(test_client, admin_headers, thread_id)
        await _delete_project(test_client, admin_headers, project_a, directory_a)
        await _delete_project(test_client, admin_headers, project_b, directory_b)
        await _delete_agent(test_client, admin_headers, slug)


async def test_project_agent_management_is_private_to_project_owner(test_client, admin_headers, standard_user):
    """非项目成员看不到、管不了项目数字员工，也不能把智能体绑定到他人项目。"""
    project_id, directory = await _create_project(test_client, admin_headers, "private")
    agent = await _create_project_agent(test_client, admin_headers, project_id, name=_agent_name("private"))
    user_headers = standard_user["headers"]
    own_agent_slug: str | None = None
    try:
        assert agent["slug"] not in await _global_agent_slugs(test_client, user_headers)

        manage_list = await test_client.get(f"/api/projects/{project_id}/agents", headers=user_headers)
        assert manage_list.status_code == 404, manage_list.text

        own_agent = await test_client.post(
            "/api/agent",
            headers=user_headers,
            json={"name": _agent_name("private-own"), "backend_id": "ChatbotAgent"},
        )
        assert own_agent.status_code == 200, own_agent.text
        own_agent_slug = own_agent.json()["agent"]["slug"]

        bind = await test_client.post(
            f"/api/projects/{project_id}/agents/bind",
            headers=user_headers,
            json={"agent_slug": own_agent_slug},
        )
        assert bind.status_code == 404, bind.text

        thread = await test_client.post(
            "/api/chat/thread",
            headers=user_headers,
            json={
                "agent_id": agent["slug"],
                "project_id": project_id,
                "title": make_test_conversation_title("project-agent-private"),
                "metadata": make_test_conversation_metadata("project-agent-private"),
            },
        )
        assert thread.status_code == 404, thread.text
    finally:
        await _delete_project(test_client, admin_headers, project_id, directory)
        await _delete_agent(test_client, admin_headers, agent["slug"])
        if own_agent_slug:
            await _delete_agent(test_client, user_headers, own_agent_slug)


async def test_execution_config_validation_and_section_reset(test_client, admin_headers):
    """sandbox/coding 在写入边界校验并真实落库；项目覆盖可整段恢复继承。"""
    project_id, directory = await _create_project(test_client, admin_headers, "execution")
    agent = await _create_project_agent(
        test_client, admin_headers, project_id, name=_agent_name("execution")
    )
    slug = agent["slug"]
    standalone_slug: str | None = None
    try:
        invalid_sandbox = await test_client.put(
            f"/api/projects/{project_id}/agents/{slug}",
            headers=admin_headers,
            json={"config_json": {"sandbox": {"mode": "invalid"}}},
        )
        assert invalid_sandbox.status_code == 422, invalid_sandbox.text
        invalid_coding = await test_client.put(
            f"/api/projects/{project_id}/agents/{slug}",
            headers=admin_headers,
            json={"config_json": {"coding": {"executors": ["unknown-executor"]}}},
        )
        assert invalid_coding.status_code == 422, invalid_coding.text

        listed = await test_client.get(f"/api/projects/{project_id}/agents", headers=admin_headers)
        assert listed.status_code == 200, listed.text
        item = next(entry for entry in listed.json()["agents"] if entry["slug"] == slug)
        assert "sandbox" not in item["config_overrides"]
        assert "coding" not in item["config_overrides"]

        saved = await test_client.put(
            f"/api/projects/{project_id}/agents/{slug}",
            headers=admin_headers,
            json={
                "config_json": {
                    "sandbox": {
                        "mode": "dedicated",
                        "lifecycle": "persistent",
                        "idle_suspend_seconds": 600,
                    },
                    "coding": {"executors": ["opencode"], "default_executor": "opencode"},
                }
            },
        )
        assert saved.status_code == 200, saved.text
        overrides = saved.json()["config_overrides"]
        assert overrides["sandbox"]["mode"] == "dedicated"
        assert overrides["sandbox"]["idle_suspend_seconds"] == 600
        assert overrides["coding"]["default_executor"] == "opencode"

        invalid_create = await test_client.post(
            "/api/agent",
            headers=admin_headers,
            json={
                "name": _agent_name("execution-invalid"),
                "backend_id": "ChatbotAgent",
                "config_json": {"sandbox": {"mode": "bogus"}},
            },
        )
        assert invalid_create.status_code == 422, invalid_create.text

        created = await test_client.post(
            "/api/agent",
            headers=admin_headers,
            json={
                "name": _agent_name("execution-standalone"),
                "backend_id": "ChatbotAgent",
                "config_json": {
                    "sandbox": {"mode": "dedicated", "lifecycle": "persistent"},
                    "coding": {"executors": ["opencode", "codex"], "default_executor": "codex"},
                },
            },
        )
        assert created.status_code == 200, created.text
        standalone_slug = created.json()["agent"]["slug"]
        detail = await test_client.get(f"/api/agent/{standalone_slug}", headers=admin_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["agent"]["config_json"]["sandbox"]["mode"] == "dedicated"
        assert detail.json()["agent"]["config_json"]["coding"]["default_executor"] == "codex"

        reset = await test_client.put(
            f"/api/projects/{project_id}/agents/{slug}",
            headers=admin_headers,
            json={"config_json": {}, "reset_fields": ["sandbox", "coding"]},
        )
        assert reset.status_code == 200, reset.text
        assert "sandbox" not in reset.json()["config_overrides"]
        assert "coding" not in reset.json()["config_overrides"]
        assert reset.json()["config_overrides"]["context"]["system_prompt"] == "项目专属人格"
    finally:
        await _delete_project(test_client, admin_headers, project_id, directory)
        await _delete_agent(test_client, admin_headers, slug)
        if standalone_slug:
            await _delete_agent(test_client, admin_headers, standalone_slug)
