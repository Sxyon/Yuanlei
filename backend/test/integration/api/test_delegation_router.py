"""委派 HTTP 路由的授权与渠道可用性负向守卫（真实 PostgreSQL + 真实 HTTP）。"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server.routers.delegation_router import delegations
from server.routers.governance_router import governance
from server.utils.auth_middleware import get_db, get_required_user
from yuxi.delegation.multica import MulticaIssue
from yuxi.repositories.channel_delegation_repository import ChannelDelegationRepository
from yuxi.storage.postgres.models_business import ProjectWorkResult
from yuxi.workspace.workdir import Workdir
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import User

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """隔离 Schema 测试不依赖运行中的 API。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """隔离 Schema 测试没有 HTTP 资源需要清理。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """隔离 Schema 测试没有 Sandbox 资源需要清理。"""
    yield


def _scoped_manager(engine) -> PostgresManager:
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager._initialized = True
    return manager


@asynccontextmanager
async def _scoped_database(prefix: str):
    """创建独立 PostgreSQL Schema 的业务表，并在退出时清理。"""
    schema = f"{prefix}_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    scoped_engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        manager = _scoped_manager(scoped_engine)
        await manager.create_business_tables()
        yield manager, async_sessionmaker(scoped_engine, expire_on_commit=False)
    finally:
        await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def _seed_user_with_project(engine, *, uid: str, project_id: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (username, uid, password_hash, role, login_failed_count, is_deleted) "
                "VALUES (:username, :uid, 'x', 'user', 0, 0)"
            ),
            {"username": f"user-{uid}", "uid": uid},
        )
        await connection.execute(
            text(
                "INSERT INTO projects (id, uid, name, selection_status, status, workdir_path, directory_mode) "
                "VALUES (:project_id, :uid, 'Pytest', 'selectable', 'active', :workdir, 'managed')"
            ),
            {"project_id": project_id, "uid": uid, "workdir": f"projects/{project_id}"},
        )


def _build_app(session_factory, *, current_user: User | None):
    """按需覆盖 get_required_user；不覆盖时保留真实 401 语义。"""
    app = FastAPI()
    app.include_router(delegations, prefix="/api")
    app.include_router(governance, prefix="/api")

    async def override_db():
        async with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    if current_user is not None:

        async def override_user():
            return current_user

        app.dependency_overrides[get_required_user] = override_user
    return app


@asynccontextmanager
async def _http_client(session_factory, *, current_user: User | None):
    app = _build_app(session_factory, current_user=current_user)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://pytest") as client:
        yield client


async def test_delegation_routes_require_authentication() -> None:
    """未认证请求由 get_required_user 拒绝为 401，而不是业务层放行。"""
    async with _scoped_database("pytest_delegation_http_anon") as (manager, sessions):
        await _seed_user_with_project(manager.async_engine, uid="uid-owner", project_id="project-owner")
        async with _http_client(sessions, current_user=None) as client:
            response = await client.get("/api/projects/project-owner/delegations")
            assert response.status_code == 401, response.text
            assert response.json()["detail"] == "请登录后再访问"


async def test_delegation_routes_reject_unknown_or_invisible_project() -> None:
    """未知 Project 与不属于当前用户的 Project 都按 404 失败。"""
    async with _scoped_database("pytest_delegation_http_project") as (manager, sessions):
        await _seed_user_with_project(manager.async_engine, uid="uid-owner", project_id="project-owner")

        owner = User(username="owner", uid="uid-owner", password_hash="x", role="user")
        other = User(username="other", uid="uid-other", password_hash="x", role="user")

        async with _http_client(sessions, current_user=owner) as client:
            unknown = await client.get(f"/api/projects/{uuid.uuid4()}/delegations")
            assert unknown.status_code == 404, unknown.text

        async with _http_client(sessions, current_user=other) as client:
            invisible = await client.get("/api/projects/project-owner/delegations")
            assert invisible.status_code == 404, invisible.text


async def test_multica_channel_routes_fail_closed_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少 Multica 凭据时渠道入口返回 503 channel_unavailable，不伪装成功。"""
    monkeypatch.delenv("YUANLEI_MULTICA_BASE_URL", raising=False)
    monkeypatch.delenv("YUANLEI_MULTICA_TOKEN", raising=False)
    async with _scoped_database("pytest_delegation_http_channel") as (manager, sessions):
        await _seed_user_with_project(manager.async_engine, uid="uid-owner", project_id="project-owner")
        owner = User(username="owner", uid="uid-owner", password_hash="x", role="user")

        async with _http_client(sessions, current_user=owner) as client:
            sync_response = await client.post("/api/projects/project-owner/channels/multica/sync")
            assert sync_response.status_code == 503, sync_response.text
            assert sync_response.json()["detail"]["code"] == "channel_unavailable"

            cursor_response = await client.get("/api/projects/project-owner/channels/multica/cursor")
            assert cursor_response.status_code == 503, cursor_response.text
            assert cursor_response.json()["detail"]["code"] == "channel_unavailable"


async def test_project_governance_http_creation_and_local_delegation_guard() -> None:
    """真实 HTTP 允许项目内治理写入，未经审核任务不得进入本地执行。"""
    async with _scoped_database("pytest_project_workbench_http") as (manager, sessions):
        await _seed_user_with_project(manager.async_engine, uid="uid-owner", project_id="project-owner")
        owner = User(username="owner", uid="uid-owner", password_hash="x", role="user")
        async with _http_client(sessions, current_user=owner) as client:
            topic = await client.post(
                "/api/projects/project-owner/governance/topics",
                json={"title": "本地议题", "source_channel": "project"},
            )
            assert topic.status_code == 200, topic.text
            reviewed = await client.post(
                f"/api/projects/project-owner/governance/topics/{topic.json()['id']}/review",
                json={"approve": True, "review_note": "纳入研讨"},
            )
            assert reviewed.status_code == 200, reviewed.text
            assert reviewed.json()["admission_status"] == "canonical"
            decision = await client.post(
                "/api/projects/project-owner/governance/decisions",
                json={"title": "采用本地方案", "conclusion": "先完成单项目", "topic_id": topic.json()["id"]},
            )
            assert decision.status_code == 200, decision.text
            task = await client.post(
                "/api/projects/project-owner/governance/tasks",
                json={"title": "本地任务", "decision_id": decision.json()["id"]},
            )
            assert task.status_code == 200, task.text
            blocked = await client.post(
                f"/api/projects/project-owner/governance/tasks/{task.json()['id']}/delegations",
                json={"executor_key": "codex"},
            )
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["detail"]["code"] == "formal_work_required"
            generic = await client.post(
                "/api/projects/project-owner/delegations",
                json={"executor_key": "codex", "task": "不能绕过任务"},
            )
            assert generic.status_code == 422, generic.text
            assert any(error["loc"][-1] == "work_task_id" for error in generic.json()["detail"])


@pytest.mark.parametrize(
    ("status", "code"),
    [("in_progress", "multica_result_not_ready"), ("done", "multica_result_unverified")],
)
async def test_multica_collect_http_rejects_projection_and_releases_lease(status, code, tmp_path, monkeypatch):
    """真实 HTTP/PG/Workdir 入口返回拒绝且保留可观察状态，无成功副作用。"""
    root = tmp_path / "shared" / "uid-owner" / "workspace" / "projects" / "project-owner"
    root.mkdir(parents=True)
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    workdir = Workdir.open_existing("uid-owner", "projects/project-owner")
    workdir.create_file("/existing.txt", b"original-bytes")

    class ProjectionClient:
        """只替代远端读取，实际 Adapter、Service 和 HTTP 错误映射均保留。"""

        async def get_issue(self, *, issue_ref):
            return MulticaIssue(
                id="i",
                identifier=issue_ref,
                title="T",
                description="http-description-sentinel",
                status=status,
                url="https://multica.invalid/issues/YL-1",
            )

    monkeypatch.setattr("yuxi.services.delegation_service.build_multica_client_from_env", lambda: ProjectionClient())
    async with _scoped_database("pytest_multica_collect_http") as (manager, sessions):
        await _seed_user_with_project(manager.async_engine, uid="uid-owner", project_id="project-owner")
        async with sessions() as db:
            await db.execute(
                text(
                    "INSERT INTO project_work_tasks "
                    "(id,project_id,number,title,status,created_by,created_at,updated_at) "
                    "VALUES ('work','project-owner','TEST-GEN-000001','虚构工作','todo','uid-owner',NOW(),NOW())"
                )
            )
            row = await ChannelDelegationRepository(db).add_delegation(
                operation_id="http-collect",
                project_id="project-owner",
                executor_key="multica",
                task="虚构任务",
                request_json={},
                initiator_run_id=None,
                created_by="uid-owner",
            )
            row.work_task_id = "work"
            row.external_ref = "YL-1"
            row.dispatch_state = "dispatched"
            await db.commit()
        user = User(username="owner", uid="uid-owner", password_hash="x", role="user")
        async with _http_client(sessions, current_user=user) as client:
            rejected = await client.post("/api/projects/project-owner/delegations/http-collect/collect")
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["detail"]["code"] == code
            assert "http-description-sentinel" not in rejected.text
            observed = await client.get("/api/projects/project-owner/delegations/http-collect")
            assert observed.status_code == 200, observed.text
            assert observed.json()["dispatch_state"] == "dispatched"
            assert observed.json()["remote_status"] == status
        async with sessions() as db:
            row = await ChannelDelegationRepository(db).get_by_operation_id(operation_id="http-collect")
            assert row.dispatch_state == "dispatched" and row.owner_token is None and row.lease_expires_at is None
            assert row.result_json == {} and row.result_summary is None and row.artifact_path is None
            assert await db.scalar(select(func.count()).select_from(ProjectWorkResult)) == 0
        assert workdir.read_file("/existing.txt", max_bytes=100) == b"original-bytes"
        assert not (root / ".yuanlei").exists()
