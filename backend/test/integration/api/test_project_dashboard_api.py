"""项目 Dashboard 页面读接口的真实 HTTP integration 测试。"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test.live_api_cleanup import make_test_resource_id

from yuxi.repositories.project_repository import ProjectRepository
from yuxi.services.project_dashboard_service import write_project_dashboard_view
from yuxi.storage.postgres.models_business import User
from yuxi.workspace import Workspace

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _create_project(test_client, headers, label: str) -> tuple[str, str]:
    """创建 linked Project，返回 (project_id, workspace directory)。"""
    directory = f"pytest-project-dashboard-{label}-{uuid.uuid4().hex[:10]}"
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
            "request_id": make_test_resource_id(f"project-dashboard-{label}"),
            "name": f"pytest-project-dashboard-{label}",
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


async def _write_page(test_client, headers, project_id: str, html: str) -> str:
    """用受控 writer 写入页面，返回 workdir_path。"""
    me = await test_client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    uid = str(me.json()["uid"])

    engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            user = await session.scalar(select(User).where(User.uid == uid))
            assert user is not None
            project = await ProjectRepository(session).get_for_user(project_id, uid)
            assert project is not None
            written = await write_project_dashboard_view(
                project_id=project_id,
                expected_revision=0,
                html=html,
                db=session,
                user=user,
            )
            assert written["revision"] == 1
            return project.workdir_path
    finally:
        await engine.dispose()


async def test_project_dashboard_pages_are_project_scoped(test_client, admin_headers):
    """同一用户的两个 Project 各自读回自己的页面。"""
    alpha_id, alpha_directory = await _create_project(test_client, admin_headers, "alpha")
    beta_id, beta_directory = await _create_project(test_client, admin_headers, "beta")
    try:
        await _write_page(test_client, admin_headers, alpha_id, "<html><body>alpha-page</body></html>")
        await _write_page(test_client, admin_headers, beta_id, "<html><body>beta-page</body></html>")

        alpha = await test_client.get(f"/api/projects/{alpha_id}/dashboard", headers=admin_headers)
        beta = await test_client.get(f"/api/projects/{beta_id}/dashboard", headers=admin_headers)
        assert alpha.status_code == 200, alpha.text
        assert beta.status_code == 200, beta.text
        assert alpha.json()["state"] == "ready"
        assert alpha.json()["html"] == "<html><body>alpha-page</body></html>"
        assert beta.json()["state"] == "ready"
        assert beta.json()["html"] == "<html><body>beta-page</body></html>"
        assert alpha.json()["sha256"] != beta.json()["sha256"]
    finally:
        await _delete_project(test_client, admin_headers, alpha_id, alpha_directory)
        await _delete_project(test_client, admin_headers, beta_id, beta_directory)


async def test_project_dashboard_read_reports_empty_ready_and_repair(test_client, admin_headers, standard_user):
    """HTTP 读接口暴露 empty/ready/repair_required，且跨用户不可见。"""
    project_id, directory = await _create_project(test_client, admin_headers, "states")
    dashboard_url = f"/api/projects/{project_id}/dashboard"
    try:
        empty = await test_client.get(dashboard_url, headers=admin_headers)
        assert empty.status_code == 200, empty.text
        assert empty.json() == {
            "state": "empty",
            "revision": 0,
            "sha256": None,
            "size": None,
            "updated_at": None,
            "html": None,
        }

        me = await test_client.get("/api/auth/me", headers=admin_headers)
        assert me.status_code == 200, me.text
        uid = str(me.json()["uid"])

        engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as session:
                user = await session.scalar(select(User).where(User.uid == uid))
                assert user is not None
                project = await ProjectRepository(session).get_for_user(project_id, uid)
                assert project is not None
                workdir_path = project.workdir_path
                written = await write_project_dashboard_view(
                    project_id=project_id,
                    expected_revision=0,
                    html="<html><body>http-v1</body></html>",
                    db=session,
                    user=user,
                )
                assert written["revision"] == 1
        finally:
            await engine.dispose()

        ready = await test_client.get(dashboard_url, headers=admin_headers)
        assert ready.status_code == 200, ready.text
        assert ready.json()["state"] == "ready"
        assert ready.json()["revision"] == 1
        assert ready.json()["html"] == "<html><body>http-v1</body></html>"

        Workspace(uid).replace_authorized_file(
            f"/{workdir_path}/dashboard/index.html",
            b"<html><body>external</body></html>",
        )
        repair = await test_client.get(dashboard_url, headers=admin_headers)
        assert repair.status_code == 200, repair.text
        assert repair.json()["state"] == "repair_required"
        assert repair.json()["revision"] == 1
        assert repair.json()["html"] is None

        other = await test_client.get(dashboard_url, headers=standard_user["headers"])
        assert other.status_code == 404
    finally:
        await _delete_project(test_client, admin_headers, project_id, directory)
