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
        topic_id = f"pytest-topic-{marker}"
        await db.execute(
            text(
                "INSERT INTO governance_topics (id, project_id, title, status, source_channel, created_at, updated_at) "
                "VALUES (:id, :project_id, 'Integration topic', 'proposed', 'project', NOW(), NOW())"
            ),
            {"id": topic_id, "project_id": project_id},
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
        missing_code = await test_client.post(f"{root}/tasks", headers=headers, json={"title": "Before setup"})
        assert missing_code.status_code == 409
        assert missing_code.json()["detail"]["code"] == "project_code_required"
        configured = await test_client.put(f"{root}/code", headers=headers, json={"code": code})
        assert configured.status_code == 200, configured.text
        assert (await test_client.get(f"{root}/code", headers=headers)).json()["code"] == code
        invalid_creation = await test_client.post(
            f"{root}/tasks", headers=headers,
            json={"title": "Invalid plan", "start_date": "2026-10-08", "due_date": "2026-10-01"},
        )
        assert invalid_creation.status_code == 422
        created = await test_client.post(
            f"{root}/tasks",
            headers=headers,
            json={"title": "Integration task", "primary_owner_agent_slug": agent_slug,
                  "start_date": "2026-10-01", "due_date": "2026-10-08"},
        )
        assert created.status_code == 200, created.text
        task = created.json()
        assert task["number"] == f"{code}-GEN-000001"
        assert (task["start_date"], task["due_date"]) == ("2026-10-01", "2026-10-08")
        task_id = task["id"]
        invalid_plan = await test_client.patch(
            f"{root}/tasks/{task_id}", headers=headers, json={"due_date": "2026-09-30"}
        )
        assert invalid_plan.status_code == 422
        assert (await test_client.get(f"{root}/tasks/{task_id}", headers=headers)).json()["due_date"] == "2026-10-08"
        changed_plan = await test_client.patch(
            f"{root}/tasks/{task_id}", headers=headers, json={"due_date": "2026-10-12"}
        )
        assert changed_plan.status_code == 200 and changed_plan.json()["due_date"] == "2026-10-12"
        topics_path = f"{root}/topics"
        assert (await test_client.get(topics_path, headers=outsider_headers)).status_code == 404
        listed_topics = await test_client.get(topics_path, headers=headers)
        assert listed_topics.status_code == 200, listed_topics.text
        assert listed_topics.json() == [
            {"id": topic_id, "title": "Integration topic", "status": "proposed", "code": None}
        ]
        no_topic_code = await test_client.post(
            f"{root}/tasks", headers=headers, json={"title": "Topic before code", "topic_id": topic_id}
        )
        assert no_topic_code.status_code == 409
        assert no_topic_code.json()["detail"]["code"] == "topic_code_required"
        topic_code = f"T{uuid.uuid4().hex[:6].upper()}"
        assert (await test_client.put(
            f"{root}/topics/{topic_id}/code", headers=outsider_headers, json={"code": topic_code}
        )).status_code == 404
        assert (await test_client.put(
            f"/api/projects/{other_id}/work/topics/{topic_id}/code", headers=headers, json={"code": topic_code}
        )).status_code == 404
        configured_topic = await test_client.put(
            f"{root}/topics/{topic_id}/code", headers=headers, json={"code": topic_code}
        )
        assert configured_topic.status_code == 200, configured_topic.text
        assert configured_topic.json() == {"topic_id": topic_id, "code": topic_code}
        assert (await test_client.put(
            f"{root}/topics/{topic_id}/code", headers=headers, json={"code": topic_code}
        )).status_code == 200
        assert (await test_client.put(
            f"{root}/topics/{topic_id}/code", headers=headers, json={"code": f"X{topic_code}"}
        )).status_code == 409
        topic_task = await test_client.post(
            f"{root}/tasks", headers=headers, json={"title": "Topic task", "topic_id": topic_id}
        )
        assert topic_task.status_code == 200, topic_task.text
        assert topic_task.json()["number"] == f"{code}-{topic_code}-000002"
        assert topic_task.json()["topic_id"] == topic_id
        assert (await test_client.get(topics_path, headers=headers)).json()[0]["code"] == topic_code
        references_path = f"{root}/tasks/{task_id}/references"
        assert (await test_client.post(
            references_path, headers=headers, json={"title": "Unsafe", "url": "javascript:alert(1)"}
        )).status_code == 422
        assert (await test_client.post(
            references_path, headers=headers, json={"title": "Credentials", "url": "https://user:pass@example.com"}
        )).status_code == 422
        for invalid_url in (
            "https://example.com:abc/path", "https://example.com:99999/path",
            "https://%20example.com/path", "https:example.com", "https:/example.com",
        ):
            assert (await test_client.post(
                references_path, headers=headers, json={"title": "Invalid", "url": invalid_url}
            )).status_code == 422
        assert (await test_client.post(
            references_path, headers=outsider_headers, json={"title": "Hidden", "url": "https://example.com"}
        )).status_code == 404
        reference = await test_client.post(
            references_path, headers=headers, json={"title": "Design", "url": "https://example.com/spec"}
        )
        assert reference.status_code == 200, reference.text
        reference_id = reference.json()["id"]
        assert reference.json()["created_by"] == uid
        assert (await test_client.get(f"{root}/tasks/{task_id}", headers=headers)).json()["references"] == [
            reference.json()
        ]
        assert (await test_client.delete(
            f"/api/projects/{other_id}/work/tasks/{task_id}/references/{reference_id}", headers=headers
        )).status_code == 404
        assert (await test_client.delete(
            f"{references_path}/{reference_id}", headers=outsider_headers
        )).status_code == 404
        async with engine.connect() as db:
            assert await db.scalar(text(
                "SELECT count(*) FROM project_work_references WHERE id = :id"
            ), {"id": reference_id}) == 1
        removed = await test_client.delete(f"{references_path}/{reference_id}", headers=headers)
        assert removed.status_code == 200 and removed.json()["deleted"] is True
        assert (await test_client.get(f"{root}/tasks/{task_id}", headers=headers)).json()["references"] == []
        rejected_delete = await test_client.delete(f"/api/agent/{agent_slug}", headers=headers)
        assert rejected_delete.status_code == 409, rejected_delete.text
        execution_task = await test_client.post(
            f"{root}/tasks", headers=headers, json={"title": "Queue task"}
        )
        assert execution_task.status_code == 200, execution_task.text
        execution_task_id = execution_task.json()["id"]
        assignment_path = f"{root}/tasks/{execution_task_id}/executions"
        assert (await test_client.post(
            assignment_path, headers=outsider_headers, json={"agent_slug": agent_slug}
        )).status_code == 404
        assigned = await test_client.post(assignment_path, headers=headers, json={"agent_slug": agent_slug})
        assert assigned.status_code == 200, assigned.text
        execution_id = assigned.json()["id"]
        assert assigned.json()["status"] == "pending_acceptance"
        assert (await test_client.post(
            assignment_path, headers=headers, json={"agent_slug": agent_slug}
        )).status_code == 409
        assert (await test_client.patch(
            f"{root}/tasks/{execution_task_id}", headers=headers, json={"status": "done"}
        )).status_code == 409
        workbench_path = f"/api/projects/{project_id}/agents/{agent_slug}/workbench"
        assert (await test_client.get(workbench_path, headers=outsider_headers)).status_code == 404
        workbench = await test_client.get(workbench_path, headers=headers)
        assert workbench.status_code == 200, workbench.text
        assert workbench.json()["auto_accept_work"] is False
        assert workbench.json()["work_default_model_spec"] is None
        assert [item["id"] for item in workbench.json()["pending_acceptance"]] == [execution_id]
        config_path = f"{workbench_path}/config"
        assert (await test_client.put(
            config_path, headers=outsider_headers,
            json={"auto_accept_work": True, "work_default_model_spec": None},
        )).status_code == 404
        invalid_model = await test_client.put(
            config_path, headers=headers,
            json={"auto_accept_work": True, "work_default_model_spec": "missing:no-such-chat-model"},
        )
        assert invalid_model.status_code == 422, invalid_model.text
        assert (await test_client.get(workbench_path, headers=headers)).json()["auto_accept_work"] is False
        configured_queue = await test_client.put(
            config_path, headers=headers,
            json={"auto_accept_work": True, "work_default_model_spec": None},
        )
        assert configured_queue.status_code == 200 and configured_queue.json()["auto_accept_work"] is True
        reset_queue = await test_client.put(
            config_path, headers=headers,
            json={"auto_accept_work": False, "work_default_model_spec": None},
        )
        assert reset_queue.status_code == 200 and reset_queue.json()["auto_accept_work"] is False
        assert (await test_client.get(assignment_path, headers=headers)).json()[0]["id"] == execution_id
        async with engine.connect() as db:
            assert await db.scalar(text(
                "SELECT status FROM project_work_executions WHERE id = :id"
            ), {"id": execution_id}) == "pending_acceptance"
        cancelled = await test_client.post(
            f"{assignment_path}/{execution_id}/cancel", headers=headers
        )
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled", cancelled.text
        assert (await test_client.post(
            f"{assignment_path}/{execution_id}/cancel", headers=outsider_headers
        )).status_code == 404
        assert (await test_client.post(
            f"{assignment_path}/{execution_id}/cancel", headers=headers
        )).status_code == 409
        reassigned = await test_client.post(assignment_path, headers=headers, json={"agent_slug": agent_slug})
        assert reassigned.status_code == 200 and reassigned.json()["id"] != execution_id, reassigned.text
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
