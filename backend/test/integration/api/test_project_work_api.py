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
    task_id = None
    try:
        root = f"/api/projects/{project_id}/work"
        code = f"W{uuid.uuid4().hex[:8].upper()}"
        assert (await test_client.get(f"{root}/code", headers=headers)).json() == {
            "project_id": project_id, "code": None
        }
        assert (await test_client.get(f"{root}/code", headers=outsider_headers)).status_code == 404
        configured = await test_client.put(f"{root}/code", headers=headers, json={"code": code})
        assert configured.status_code == 200, configured.text
        assert (await test_client.get(f"{root}/code", headers=headers)).json()["code"] == code
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

        completed = await test_client.patch(f"{root}/tasks/{task_id}", headers=headers, json={"status": "done"})
        assert completed.status_code == 200, completed.text
        unread = await test_client.get("/api/inbox?folder=unread", headers=headers)
        assert unread.status_code == 200, unread.text
        notices = [item for item in unread.json() if item["source_id"] == task_id]
        assert len(notices) == 1 and notices[0]["kind"] == "task_completed"
        notice_id = notices[0]["id"]
        async with engine.connect() as db:
            assert (
                await db.scalar(text("SELECT count(*) FROM user_inbox_items WHERE source_id = :id"), {"id": task_id})
                == 1
            )
        outsider_notice = await test_client.patch(
            f"/api/inbox/{notice_id}", headers=outsider_headers, json={"read": True}
        )
        assert outsider_notice.status_code == 404
        read_notice = await test_client.patch(f"/api/inbox/{notice_id}", headers=headers, json={"read": True})
        assert read_notice.status_code == 200 and read_notice.json()["read_at"]
        archived_notice = await test_client.patch(f"/api/inbox/{notice_id}", headers=headers, json={"archived": True})
        assert archived_notice.status_code == 200 and archived_notice.json()["archived_at"]
        archived_list = await test_client.get("/api/inbox?folder=archived", headers=headers)
        assert any(item["id"] == notice_id for item in archived_list.json())
        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO user_inbox_items (id, uid, kind, source_id, title) "
                    "SELECT :prefix || '-' || n, :uid, 'run_question', :prefix || '-' || n, 'Question' "
                    "FROM generate_series(1, 51) AS n"
                ),
                {"prefix": f"notice-{marker}", "uid": uid},
            )
        first_page = await test_client.get("/api/inbox?folder=unread", headers=headers)
        assert len(first_page.json()) == 50
        moved = await test_client.patch(
            f"/api/inbox/{first_page.json()[0]['id']}", headers=headers, json={"read": True}
        )
        assert moved.status_code == 200
        cursor = first_page.json()[-1]["id"]
        second_page = await test_client.get(f"/api/inbox?folder=unread&before={cursor}", headers=headers)
        assert len(second_page.json()) == 1
        assert second_page.json()[0]["id"] not in {item["id"] for item in first_page.json()}
        assert (await test_client.get("/api/inbox?folder=unread&before=missing", headers=headers)).status_code == 422
        assert (
            await test_client.get(f"/api/inbox?folder=unread&before={cursor}", headers=outsider_headers)
        ).status_code == 422
        assert (await test_client.get("/api/inbox?folder=unread", headers=outsider_headers)).json() == []

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
        assert (await test_client.get(f"{root}/code", headers=headers)).status_code == 404
    finally:
        async with engine.begin() as db:
            await db.execute(text("DELETE FROM user_inbox_items WHERE uid = :uid"), {"uid": uid})
            await db.execute(
                text("DELETE FROM projects WHERE id IN (:first, :second)"),
                {"first": project_id, "second": other_id},
            )
            await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": outsider_id})
            await db.execute(text("DELETE FROM departments WHERE id = :id"), {"id": department_id})
            await db.execute(text("DELETE FROM agents WHERE slug = :slug"), {"slug": agent_slug})
        await engine.dispose()
