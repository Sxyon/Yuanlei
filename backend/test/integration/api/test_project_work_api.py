"""项目工作任务真实 HTTP 权限与协议测试。"""

from __future__ import annotations

import os
import uuid
import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from yuxi.repositories.agent_repository import DEFAULT_SHARE_CONFIG
from yuxi.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_project_work_http_lifecycle_and_cross_project_guards(test_client):
    """HTTP 创建、评论和问题单可回读，跨项目任务路径不可见。"""
    marker = uuid.uuid4().hex[:12]
    uid = f"pytest-work-{marker}"
    project_id = f"pytest-work-main-{marker}"
    other_id = f"pytest-work-other-{marker}"
    agent_slug = f"pytest-work-agent-{marker}"
    engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    async with engine.begin() as db:
        department_id = await db.scalar(
            text("INSERT INTO departments (name) VALUES (:name) RETURNING id"),
            {"name": uid},
        )
        user_id = await db.scalar(
            text(
                "INSERT INTO users (username, uid, password_hash, role, department_id, login_failed_count, is_deleted) "
                "VALUES (:uid, :uid, 'x', 'user', :department_id, 0, 0) RETURNING id"
            ),
            {"uid": uid, "department_id": department_id},
        )
        outsider_id = await db.scalar(
            text(
                "INSERT INTO users (username, uid, password_hash, role, department_id, login_failed_count, is_deleted) "
                "VALUES (:uid, :uid, 'x', 'user', :department_id, 0, 0) RETURNING id"
            ),
            {"uid": f"{uid}-outsider", "department_id": department_id},
        )
        for pid in (project_id, other_id):
            await db.execute(
                text(
                    "INSERT INTO projects (id, uid, name, selection_status, workdir_path, directory_mode) "
                    "VALUES (:id, :uid, 'Pytest', 'selectable', :path, 'managed')"
                ),
                {"id": pid, "uid": uid, "path": f"projects/{pid}"},
            )
        await db.execute(
            text(
                "INSERT INTO agents "
                "(slug, backend_id, name, pics, config_json, share_config, is_default, is_subagent, created_by) "
                "VALUES (:slug, 'ChatbotAgent', 'Work Agent', '[]'::jsonb, '{}'::jsonb, "
                "CAST(:share_config AS jsonb), FALSE, FALSE, :uid)"
            ),
            {"slug": agent_slug, "uid": uid, "share_config": json.dumps(DEFAULT_SHARE_CONFIG)},
        )
        await db.execute(
            text(
                "INSERT INTO project_agents (id, project_id, agent_slug, config_overrides) "
                "VALUES (:id, :project_id, :slug, '{}'::jsonb)"
            ),
            {"id": f"pytest-binding-{marker}", "project_id": project_id, "slug": agent_slug},
        )
    headers = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(user_id)})}"}
    outsider_headers = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(outsider_id)})}"}
    try:
        root = f"/api/projects/{project_id}/work"
        code = f"W{uuid.uuid4().hex[:8].upper()}"
        configured = await test_client.put(f"{root}/code", headers=headers, json={"code": code})
        assert configured.status_code == 200, configured.text
        created = await test_client.post(
            f"{root}/tasks",
            headers=headers,
            json={"title": "Integration task", "primary_owner_agent_slug": agent_slug},
        )
        assert created.status_code == 200, created.text
        task = created.json()
        assert task["number"] == f"{code}-GEN-000001"
        task_id = task["id"]
        rejected_delete = await test_client.delete(f"/api/agent/{agent_slug}", headers=headers)
        assert rejected_delete.status_code == 409, rejected_delete.text
        issue_response = await test_client.post(
            f"{root}/tasks/{task_id}/issues",
            headers=headers,
            json={"title": "Integration issue"},
        )
        assert issue_response.status_code == 200, issue_response.text
        issue_id = issue_response.json()["id"]
        comment = await test_client.post(
            f"{root}/tasks/{task_id}/issues/{issue_id}/comments",
            headers=headers,
            json={"content": "Verified outcome"},
        )
        assert comment.status_code == 200, comment.text
        detail = await test_client.get(f"{root}/tasks/{task_id}/issues/{issue_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert [item["content"] for item in detail.json()["comments"]] == ["Verified outcome"]

        foreign = await test_client.get(
            f"/api/projects/{other_id}/work/tasks/{task_id}",
            headers=headers,
        )
        assert foreign.status_code == 404
        outsider = await test_client.get(f"{root}/tasks/{task_id}", headers=outsider_headers)
        assert outsider.status_code == 404
        unauthenticated = await test_client.get(f"{root}/tasks/{task_id}")
        assert unauthenticated.status_code == 401
        async with engine.begin() as db:
            await db.execute(text("UPDATE projects SET status = 'deleted' WHERE id = :id"), {"id": project_id})
        deleted = await test_client.get(f"{root}/tasks/{task_id}", headers=headers)
        assert deleted.status_code == 404
    finally:
        async with engine.begin() as db:
            await db.execute(
                text("DELETE FROM projects WHERE id IN (:first, :second)"),
                {"first": project_id, "second": other_id},
            )
            await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": outsider_id})
            await db.execute(text("DELETE FROM departments WHERE id = :id"), {"id": department_id})
            await db.execute(text("DELETE FROM agents WHERE slug = :slug"), {"slug": agent_slug})
        await engine.dispose()
