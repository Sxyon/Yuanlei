"""项目命名 JSON 文档的真实 HTTP integration 测试。"""

from __future__ import annotations

import uuid

import pytest
from test.live_api_cleanup import make_test_resource_id

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _create_project(test_client, headers, label: str) -> tuple[str, str]:
    """创建 linked Project，返回 (project_id, workspace directory)。"""
    directory = f"pytest-project-document-{label}-{uuid.uuid4().hex[:10]}"
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
            "request_id": make_test_resource_id(f"project-document-{label}"),
            "name": f"pytest-project-document-{label}",
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


async def test_project_document_versions_and_scope(test_client, admin_headers, standard_user):
    """HTTP 契约：创建/替换推进 version，过期写入 409，跨用户与非法 key fail-closed。"""
    project_id, directory = await _create_project(test_client, admin_headers, "versions")
    document_url = f"/api/projects/{project_id}/documents/dashboard.config"
    try:
        created = await test_client.put(
            document_url,
            headers=admin_headers,
            json={"expected_version": 0, "content": {"layout": "cards"}},
        )
        assert created.status_code == 200, created.text
        assert created.json()["version"] == 1

        read = await test_client.get(document_url, headers=admin_headers)
        assert read.status_code == 200, read.text
        assert read.json()["content"] == {"layout": "cards"}
        assert read.json()["version"] == 1

        replaced = await test_client.put(
            document_url,
            headers=admin_headers,
            json={"expected_version": 1, "content": {"layout": "list"}},
        )
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["version"] == 2

        stale = await test_client.put(
            document_url,
            headers=admin_headers,
            json={"expected_version": 1, "content": {"layout": "stale"}},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"] == {"code": "version_conflict", "current_version": 2}

        invalid_key = await test_client.put(
            f"/api/projects/{project_id}/documents/Bad.Key",
            headers=admin_headers,
            json={"expected_version": 0, "content": {}},
        )
        assert invalid_key.status_code == 422

        missing = await test_client.get(
            f"/api/projects/{project_id}/documents/data.none",
            headers=admin_headers,
        )
        assert missing.status_code == 404

        other_read = await test_client.get(document_url, headers=standard_user["headers"])
        assert other_read.status_code == 404
        other_write = await test_client.put(
            document_url,
            headers=standard_user["headers"],
            json={"expected_version": 2, "content": {}},
        )
        assert other_write.status_code == 404
    finally:
        await _delete_project(test_client, admin_headers, project_id, directory)
