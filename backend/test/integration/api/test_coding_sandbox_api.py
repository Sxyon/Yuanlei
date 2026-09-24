"""专属沙盒管理 API：真实 provisioner 预热、回收与恢复。"""

from __future__ import annotations

import uuid

import pytest
from test.integration.api.test_project_agent_api import (
    _create_project,
    _delete_agent,
    _delete_project,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _create_agent(test_client, headers, *, config_json: dict | None = None) -> str:
    response = await test_client.post(
        "/api/agent",
        headers=headers,
        json={
            "name": f"pytest-coding-sandbox-{uuid.uuid4().hex[:8]}",
            "backend_id": "ChatbotAgent",
            "config_json": config_json or {},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["agent"]["slug"]


async def test_provision_suspend_and_resume_dedicated_sandbox(test_client, admin_headers):
    """预热真实创建 runtime；回收后再次预热按策略恢复；共享策略被拒绝。"""
    project_id, directory = await _create_project(test_client, admin_headers, "coding-sandbox")
    slug = await _create_agent(
        test_client,
        admin_headers,
        config_json={
            "sandbox": {"mode": "dedicated", "lifecycle": "persistent", "idle_suspend_seconds": 900}
        },
    )
    shared_slug = await _create_agent(test_client, admin_headers)
    try:
        provision = await test_client.post(
            f"/api/coding/sandboxes/{slug}/{project_id}/provision",
            headers=admin_headers,
        )
        assert provision.status_code == 200, provision.text
        view = provision.json()
        assert view["status"] == "active"
        assert view["lifecycle"] == "persistent"
        assert view["generation"]

        listed = await test_client.get("/api/coding/sandboxes", headers=admin_headers)
        assert listed.status_code == 200, listed.text
        sandbox = next(
            (item for item in listed.json()["sandboxes"] if item["agent_slug"] == slug), None
        )
        assert sandbox is not None
        assert sandbox["status"] == "active"
        assert sandbox["project_id"] == project_id

        suspended = await test_client.post(
            f"/api/coding/sandboxes/{slug}/{project_id}/suspend",
            headers=admin_headers,
        )
        assert suspended.status_code == 200, suspended.text
        assert suspended.json()["status"] == "suspended"

        resumed = await test_client.post(
            f"/api/coding/sandboxes/{slug}/{project_id}/provision",
            headers=admin_headers,
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "active"
        assert resumed.json()["generation"]

        rejected = await test_client.post(
            f"/api/coding/sandboxes/{shared_slug}/{project_id}/provision",
            headers=admin_headers,
        )
        assert rejected.status_code == 422, rejected.text
    finally:
        await _delete_agent(test_client, admin_headers, slug)
        await _delete_agent(test_client, admin_headers, shared_slug)
        await _delete_project(test_client, admin_headers, project_id, directory)
