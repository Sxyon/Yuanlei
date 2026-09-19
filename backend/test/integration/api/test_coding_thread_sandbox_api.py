"""会话视角专属沙盒状态与终端直达的真实 API 集成测试。"""

from __future__ import annotations

import uuid

import pytest
from test.integration.api.test_project_agent_api import (
    _create_project,
    _delete_agent,
    _delete_project,
    _delete_thread,
)
from test.live_api_cleanup import make_test_conversation_metadata, make_test_conversation_title

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _create_agent(test_client, headers, *, config_json: dict) -> str:
    response = await test_client.post(
        "/api/agent",
        headers=headers,
        json={
            "name": f"pytest-thread-sandbox-{uuid.uuid4().hex[:8]}",
            "backend_id": "ChatbotAgent",
            "config_json": config_json,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["agent"]["slug"]


async def _create_thread(test_client, headers, *, agent_slug: str, project_id: str) -> str:
    response = await test_client.post(
        "/api/chat/thread",
        headers=headers,
        json={
            "agent_id": agent_slug,
            "project_id": project_id,
            "title": make_test_conversation_title("thread-sandbox"),
            "metadata": make_test_conversation_metadata("thread-sandbox"),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_thread_sandbox_status_and_terminal_ensure_runtime(test_client, admin_headers):
    """专属会话暴露沙盒状态；打开终端会预热 runtime 并返回可用门票。"""
    project_id, directory = await _create_project(test_client, admin_headers, "thread-sandbox")
    dedicated_slug = await _create_agent(
        test_client,
        admin_headers,
        config_json={
            "sandbox": {"mode": "dedicated", "lifecycle": "persistent", "resume_policy": "auto"},
            "coding": {"executors": ["opencode"], "default_executor": "opencode"},
        },
    )
    shared_slug = await _create_agent(test_client, admin_headers, config_json={})
    dedicated_thread = await _create_thread(
        test_client, admin_headers, agent_slug=dedicated_slug, project_id=project_id
    )
    shared_thread = await _create_thread(
        test_client, admin_headers, agent_slug=shared_slug, project_id=project_id
    )
    try:
        shared_status = await test_client.get(
            f"/api/coding/threads/{shared_thread}/sandbox", headers=admin_headers
        )
        assert shared_status.status_code == 200, shared_status.text
        assert shared_status.json()["enabled"] is False

        status = await test_client.get(
            f"/api/coding/threads/{dedicated_thread}/sandbox", headers=admin_headers
        )
        assert status.status_code == 200, status.text
        payload = status.json()
        assert payload["enabled"] is True
        assert payload["mode"] == "dedicated"
        assert payload["scope_key"].startswith("agent-project:")

        terminal = await test_client.post(
            f"/api/coding/threads/{dedicated_thread}/terminal", headers=admin_headers
        )
        assert terminal.status_code == 200, terminal.text
        ticket = terminal.json()
        assert ticket["session_id"]
        assert ticket["ws_path"].startswith(
            f"/api/coding/sessions/{ticket['session_id']}/terminal?ticket="
        )

        warmed = await test_client.get(
            f"/api/coding/threads/{dedicated_thread}/sandbox", headers=admin_headers
        )
        assert warmed.status_code == 200, warmed.text
        sandbox = warmed.json()["sandbox"]
        assert sandbox is not None
        assert sandbox["status"] == "active"
        assert sandbox["generation"]

        # 再次打开终端应复用同一会话，不产生重复会话
        again = await test_client.post(
            f"/api/coding/threads/{dedicated_thread}/terminal", headers=admin_headers
        )
        assert again.status_code == 200, again.text
        assert again.json()["session_id"] == ticket["session_id"]

    finally:
        await _delete_thread(test_client, admin_headers, dedicated_thread)
        await _delete_thread(test_client, admin_headers, shared_thread)
        await _delete_agent(test_client, admin_headers, dedicated_slug)
        await _delete_agent(test_client, admin_headers, shared_slug)
        await _delete_project(test_client, admin_headers, project_id, directory)
