"""项目工作任务文件附件的真实 HTTP 权限、类型与大小边界测试。"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from yuxi.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _seed(engine, marker: str) -> dict:
    """创建用户、项目、数字员工绑定与任务编号配置。"""
    uid = f"pytest-attach-{marker}"
    project_id = f"pytest-attach-main-{marker}"
    other_id = f"pytest-attach-other-{marker}"
    async with engine.begin() as db:
        department_id = await db.scalar(
            text("INSERT INTO departments (name) VALUES (:name) RETURNING id"), {"name": uid}
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
    return {
        "uid": uid,
        "user_id": user_id,
        "outsider_id": outsider_id,
        "department_id": department_id,
        "project_id": project_id,
        "other_id": other_id,
    }


async def test_project_work_attachment_http_lifecycle_and_guards(test_client):
    """附件上传、下载与删除可回读，类型、大小与跨项目越权在真实边界被拒。"""
    marker = uuid.uuid4().hex[:12]
    engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    seeded = await _seed(engine, marker)
    headers = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(seeded['user_id'])})}"}
    outsider_headers = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(seeded['outsider_id'])})}"}
    project_id = seeded["project_id"]
    root = f"/api/projects/{project_id}/work"
    task_id = None
    try:
        code = await test_client.put(f"{root}/code", headers=headers, json={"code": f"A{marker.upper()[:8]}"})
        assert code.status_code == 200, code.text
        created = await test_client.post(f"{root}/tasks", headers=headers, json={"title": "Attachment task"})
        assert created.status_code == 200, created.text
        task_id = created.json()["id"]
        attachments_path = f"{root}/tasks/{task_id}/attachments"

        rejected_type = await test_client.post(
            attachments_path, headers=headers, files={"file": ("malware.exe", b"MZ", "application/octet-stream")}
        )
        assert rejected_type.status_code == 422, rejected_type.text

        oversized = await test_client.post(
            attachments_path,
            headers=headers,
            files={"file": ("big.txt", b"x" * (5 * 1024 * 1024 + 1), "text/plain")},
        )
        assert oversized.status_code == 422, oversized.text

        outsider_upload = await test_client.post(
            attachments_path, headers=outsider_headers, files={"file": ("note.txt", b"hidden", "text/plain")}
        )
        assert outsider_upload.status_code == 404

        uploaded = await test_client.post(
            attachments_path, headers=headers, files={"file": ("设计说明.txt", b"hello attachment", "text/plain")}
        )
        assert uploaded.status_code == 200, uploaded.text
        attachment = uploaded.json()
        attachment_id = attachment["id"]
        assert attachment["file_name"] == "设计说明.txt"
        assert attachment["file_size"] == len(b"hello attachment")

        detail = await test_client.get(f"{root}/tasks/{task_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert [item["id"] for item in detail.json()["attachments"]] == [attachment_id]
        async with engine.connect() as db:
            assert await db.scalar(
                text("SELECT count(*) FROM project_work_attachments WHERE id = :id"), {"id": attachment_id}
            ) == 1

        download_path = f"{attachments_path}/{attachment_id}/download"
        downloaded = await test_client.get(download_path, headers=headers)
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.content == b"hello attachment"
        assert "UTF-8''%E8%AE%BE%E8%AE%A1%E8%AF%B4%E6%98%8E.txt" in downloaded.headers["content-disposition"]

        assert (await test_client.get(download_path, headers=outsider_headers)).status_code == 404
        assert (await test_client.get(
            f"/api/projects/{seeded['other_id']}/work/tasks/{task_id}/attachments/{attachment_id}/download",
            headers=headers,
        )).status_code == 404
        assert (
            await test_client.delete(f"{attachments_path}/{attachment_id}", headers=outsider_headers)
        ).status_code == 404

        removed = await test_client.delete(f"{attachments_path}/{attachment_id}", headers=headers)
        assert removed.status_code == 200 and removed.json()["deleted"] is True
        assert (await test_client.get(f"{root}/tasks/{task_id}", headers=headers)).json()["attachments"] == []
        assert (await test_client.get(download_path, headers=headers)).status_code == 404
        async with engine.connect() as db:
            assert await db.scalar(
                text("SELECT count(*) FROM project_work_attachments WHERE id = :id"), {"id": attachment_id}
            ) == 0
    finally:
        async with engine.begin() as db:
            await db.execute(
                text("DELETE FROM projects WHERE id IN (:first, :second)"),
                {"first": project_id, "second": seeded["other_id"]},
            )
            await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": seeded["user_id"]})
            await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": seeded["outsider_id"]})
            await db.execute(text("DELETE FROM departments WHERE id = :id"), {"id": seeded["department_id"]})
        await engine.dispose()
