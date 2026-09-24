"""Dashboard Agent 工具在真实 Project 范围内的集成测试。"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.agents.toolkits.buildin import dashboard_tools
from yuxi.agents.toolkits.buildin.dashboard_tools import dashboard_read, dashboard_write
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import AgentRun, Conversation, Message, Project, User
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.workspace import filesystem as workspace_filesystem_module

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
    """创建不触碰进程单例的隔离 manager，并提供工具使用的会话工厂。"""
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager.AsyncSession = async_sessionmaker(engine, expire_on_commit=False)
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


async def _seed_run(
    sessions,
    *,
    uid: str,
    project_id: str,
    thread_id: str,
    run_id: str,
    selection_status: str = "selectable",
    workdir_path: str = "projects/p1",
    run_status: str = "running",
    worker_id: str = "worker-current",
    lease_expires_at=None,
) -> None:
    """创建 User → Project → Conversation → Run 的最小持久化链路。"""
    async with sessions() as session:
        session.add(User(username=f"user-{uid}", uid=uid, password_hash="x"))
        await session.flush()
        session.add(
            Project(
                id=project_id,
                uid=uid,
                selection_status=selection_status,
                workdir_path=workdir_path,
                directory_mode="linked",
            )
        )
        await session.flush()
        conversation = Conversation(
            thread_id=thread_id,
            uid=uid,
            project_id=project_id,
            agent_id="main",
            status="active",
        )
        session.add(conversation)
        await session.flush()
        message = Message(
            conversation_id=conversation.id,
            role="user",
            content="pytest dashboard tool",
            request_id=f"request-{run_id}",
            delivery_status="dispatched",
        )
        session.add(message)
        await session.flush()
        session.add(
            AgentRun(
                id=run_id,
                conversation_thread_id=thread_id,
                runtime_scope_id=thread_id,
                agent_slug="main",
                uid=uid,
                request_id=f"request-{run_id}",
                conversation_id=conversation.id,
                input_message_id=message.id,
                input_payload={},
                status=run_status,
                run_type="chat",
                worker_id=worker_id,
                heartbeat_at=utc_now_naive(),
                lease_expires_at=lease_expires_at or utc_now_naive() + timedelta(minutes=5),
            )
        )
        await session.commit()


async def test_dashboard_tool_reads_and_writes_only_run_project(tmp_path, monkeypatch) -> None:
    """工具沿 Run→Conversation 解析 Project，并复用受控 writer 推进 revision。"""
    workspace_root = tmp_path / "workspace"
    workdir_rel = "projects/p1"
    (workspace_root / workdir_rel).mkdir(parents=True)
    monkeypatch.setattr(workspace_filesystem_module, "user_workspace_dir", lambda _uid: workspace_root)

    async with _scoped_database("pytest_dashboard_tool") as (manager, sessions):
        await _seed_run(
            sessions,
            uid="uid-owner",
            project_id="project-owner",
            thread_id="thread-1",
            run_id="run-1",
            workdir_path=workdir_rel,
        )
        monkeypatch.setattr(dashboard_tools, "pg_manager", manager)
        runtime = SimpleNamespace(
            context=SimpleNamespace(
                run_id="run-1", uid="uid-owner", worker_id="worker-current", is_subagent_runtime=False
            )
        )

        empty = json.loads(await dashboard_read.coroutine(runtime=runtime))
        assert empty["state"] == "empty"

        written = json.loads(
            await dashboard_write.coroutine(
                html="<html><body>tool</body></html>",
                expected_revision=0,
                runtime=runtime,
            )
        )
        assert written["state"] == "ready"
        assert written["revision"] == 1

        stale = json.loads(
            await dashboard_write.coroutine(
                html="<html><body>stale</body></html>",
                expected_revision=0,
                runtime=runtime,
            )
        )
        assert stale["error_code"] == "revision_conflict"
        assert stale["current_revision"] == 1

        ready = json.loads(await dashboard_read.coroutine(runtime=runtime))
        assert ready["state"] == "ready"
        assert ready["revision"] == 1
        assert ready["html"] == "<html><body>tool</body></html>"
        assert (workspace_root / workdir_rel / "dashboard" / "index.html").read_bytes() == (
            b"<html><body>tool</body></html>"
        )


async def test_dashboard_tool_rejects_project_outside_editable_scope(tmp_path, monkeypatch) -> None:
    """隐式 Project 不进入可编辑范围，工具返回结构化不可用。"""
    workspace_root = tmp_path / "workspace"
    workdir_rel = "projects/p1"
    (workspace_root / workdir_rel).mkdir(parents=True)
    monkeypatch.setattr(workspace_filesystem_module, "user_workspace_dir", lambda _uid: workspace_root)

    async with _scoped_database("pytest_dashboard_tool_scope") as (manager, sessions):
        await _seed_run(
            sessions,
            uid="uid-owner",
            project_id="project-implicit",
            thread_id="thread-implicit",
            run_id="run-implicit",
            selection_status="implicit",
            workdir_path=workdir_rel,
        )
        monkeypatch.setattr(dashboard_tools, "pg_manager", manager)
        runtime = SimpleNamespace(
            context=SimpleNamespace(
                run_id="run-implicit", uid="uid-owner", worker_id="worker-current", is_subagent_runtime=False
            )
        )

        payload = json.loads(await dashboard_read.coroutine(runtime=runtime))
        assert payload == {
            "error_code": "invalid_request",
            "message": "当前运行无权访问项目 Dashboard",
        }


async def test_dashboard_tool_reauthorizes_running_owner_scope(tmp_path, monkeypatch) -> None:
    """工具不能信任运行时 uid，且未运行的 Root Run 不能借用 Dashboard 能力。"""
    workspace_root = tmp_path / "workspace"
    workdir_rel = "projects/p1"
    (workspace_root / workdir_rel).mkdir(parents=True)
    monkeypatch.setattr(workspace_filesystem_module, "user_workspace_dir", lambda _uid: workspace_root)

    async with _scoped_database("pytest_dashboard_tool_auth") as (manager, sessions):
        await _seed_run(
            sessions,
            uid="uid-owner",
            project_id="project-owner",
            thread_id="thread-1",
            run_id="run-1",
            workdir_path=workdir_rel,
            run_status="pending",
        )
        monkeypatch.setattr(dashboard_tools, "pg_manager", manager)

        pending_runtime = SimpleNamespace(
            context=SimpleNamespace(
                run_id="run-1", uid="uid-owner", worker_id="worker-current", is_subagent_runtime=False
            )
        )
        pending = json.loads(await dashboard_read.coroutine(runtime=pending_runtime))
        assert pending == {
            "error_code": "invalid_request",
            "message": "只有正在执行的根 AgentRun 可以访问项目 Dashboard",
        }

        spoofed_runtime = SimpleNamespace(
            context=SimpleNamespace(
                run_id="run-1", uid="uid-other", worker_id="worker-current", is_subagent_runtime=False
            )
        )
        spoofed = json.loads(await dashboard_read.coroutine(runtime=spoofed_runtime))
        assert spoofed == {
            "error_code": "invalid_request",
            "message": "当前运行无权访问项目 Dashboard",
        }


@pytest.mark.parametrize(
    ("runtime_worker_id", "lease_expires_at"),
    (
        ("worker-replaced", None),
        ("worker-current", utc_now_naive() - timedelta(seconds=1)),
    ),
    ids=["owner_mismatch", "lease_expired"],
)
async def test_dashboard_tool_rejects_non_owner_or_expired_lease(
    tmp_path, monkeypatch, runtime_worker_id, lease_expires_at
) -> None:
    """失去当前 attempt ownership 的 worker 不能读取或写入 Dashboard。"""
    workspace_root = tmp_path / "workspace"
    workdir_rel = "projects/p1"
    (workspace_root / workdir_rel).mkdir(parents=True)
    monkeypatch.setattr(workspace_filesystem_module, "user_workspace_dir", lambda _uid: workspace_root)

    async with _scoped_database("pytest_dashboard_tool_lease") as (manager, sessions):
        await _seed_run(
            sessions,
            uid="uid-owner",
            project_id="project-owner",
            thread_id="thread-1",
            run_id="run-1",
            workdir_path=workdir_rel,
            lease_expires_at=lease_expires_at,
        )
        monkeypatch.setattr(dashboard_tools, "pg_manager", manager)
        runtime = SimpleNamespace(
            context=SimpleNamespace(
                run_id="run-1", uid="uid-owner", worker_id=runtime_worker_id, is_subagent_runtime=False
            )
        )

        payload = json.loads(await dashboard_write.coroutine(
            html="<html><body>blocked</body></html>", expected_revision=0, runtime=runtime
        ))
        assert payload == {
            "error_code": "invalid_request",
            "message": "只有当前有效 AgentRun lease owner 可以访问项目 Dashboard",
        }
        assert not (workspace_root / workdir_rel / "dashboard" / "index.html").exists()
