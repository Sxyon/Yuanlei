"""项目 Dashboard revision 元数据与页面读回的真实 PostgreSQL 集成测试。"""

from __future__ import annotations

import hashlib
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yuxi.services.project_dashboard_service import MAX_PAGE_BYTES, get_project_dashboard_view
from yuxi.storage.postgres.manager import YUANLEI_SCHEMA_VERSION, PostgresManager
from yuxi.storage.postgres.models_business import User
from yuxi.workspace import filesystem as workspace_filesystem_module

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_DOCUMENT_COLUMNS = {
    "id",
    "project_id",
    "key",
    "content",
    "version",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
}
_DASHBOARD_COLUMNS = {
    "project_id",
    "revision",
    "content_sha256",
    "content_size",
    "updated_by",
    "updated_at",
}


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
    """创建不触碰进程单例的隔离 manager。"""
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


async def _seed_user(engine, *, uid: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (username, uid, password_hash, role, login_failed_count, is_deleted) "
                "VALUES (:username, :uid, 'x', 'user', 0, 0)"
            ),
            {"username": f"user-{uid}", "uid": uid},
        )


async def _seed_project(
    engine,
    *,
    project_id: str,
    uid: str,
    workdir_path: str = "projects/p1",
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO projects (id, uid, name, selection_status, workdir_path, directory_mode) "
                "VALUES (:project_id, :uid, 'Pytest', 'selectable', :workdir_path, 'linked')"
            ),
            {"project_id": project_id, "uid": uid, "workdir_path": workdir_path},
        )


async def _load_user(session: AsyncSession, uid: str) -> User:
    user = await session.scalar(select(User).where(User.uid == uid))
    assert user is not None
    return user


async def test_yuanlei_v8_to_v9_converges_dashboard_tables_idempotently() -> None:
    """真实 PostgreSQL：v8→v9 建表幂等，唯一与检查约束真实生效。"""
    async with _scoped_database("pytest_dashboard_schema") as (manager, _sessions):
        assert YUANLEI_SCHEMA_VERSION == 9
        async with manager.async_engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS project_documents, project_dashboards"))

        await manager.upgrade_yuanlei_schema_v8_to_v9()
        await manager.upgrade_yuanlei_schema_v8_to_v9()

        async with manager.async_engine.connect() as connection:
            tables = {
                row.table_name
                for row in await connection.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
                )
            }
            assert {"project_documents", "project_dashboards"} <= tables

            columns_by_table = {}
            for table_name in ("project_documents", "project_dashboards"):
                columns_by_table[table_name] = {
                    row.column_name
                    for row in await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() AND table_name = :table_name"
                        ),
                        {"table_name": table_name},
                    )
                }
            assert columns_by_table["project_documents"] == _DOCUMENT_COLUMNS
            assert columns_by_table["project_dashboards"] == _DASHBOARD_COLUMNS

            constraints = {
                row.conname
                for row in await connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid IN ('project_documents'::regclass, 'project_dashboards'::regclass)"
                    )
                )
            }
            assert {
                "uq_project_documents_project_key",
                "ck_project_documents_version",
                "fk_project_documents_project_id",
                "ck_project_dashboards_revision",
                "fk_project_dashboards_project_id",
            } <= constraints

        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(manager.async_engine, project_id="project-owner", uid="uid-owner")
        async with manager.async_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO project_documents (id, project_id, key, content, version) "
                    "VALUES ('doc-1', 'project-owner', 'dashboard.config', '{}'::jsonb, 1)"
                )
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO project_documents (id, project_id, key, content, version) "
                            "VALUES ('doc-2', 'project-owner', 'dashboard.config', '{}'::jsonb, 1)"
                        )
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO project_documents (id, project_id, key, content, version) "
                            "VALUES ('doc-3', 'project-owner', 'dashboard.config', '{}'::jsonb, 0)"
                        )
                    )


async def test_page_read_back_reports_empty_ready_and_repair_states(tmp_path: Path, monkeypatch) -> None:
    """页面状态由元数据与磁盘 hash 对账决定；外部改写不伪装成受控 revision。"""
    workspace_root = tmp_path / "workspace"
    workdir_rel = "projects/p1"
    page_path = workspace_root / workdir_rel / "dashboard" / "index.html"
    page_path.parent.mkdir(parents=True)
    monkeypatch.setattr(workspace_filesystem_module, "user_workspace_dir", lambda _uid: workspace_root)

    async with _scoped_database("pytest_dashboard_state") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(manager.async_engine, project_id="project-owner", uid="uid-owner", workdir_path=workdir_rel)
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")

            empty = await get_project_dashboard_view(project_id="project-owner", db=session, user=user)
            assert empty == {
                "state": "empty",
                "revision": 0,
                "sha256": None,
                "size": None,
                "updated_at": None,
                "html": None,
            }

            raw = b"<html><body>v1</body></html>"
            page_path.write_bytes(raw)
            orphan = await get_project_dashboard_view(project_id="project-owner", db=session, user=user)
            assert orphan["state"] == "repair_required"
            assert orphan["revision"] == 0
            assert orphan["sha256"] == hashlib.sha256(raw).hexdigest()
            assert orphan["html"] is None

            async with manager.async_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO project_dashboards "
                        "(project_id, revision, content_sha256, content_size, updated_by, updated_at) "
                        "VALUES ('project-owner', 1, :sha256, :size, 'uid-owner', NOW())"
                    ),
                    {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)},
                )

            ready = await get_project_dashboard_view(project_id="project-owner", db=session, user=user)
            assert ready["state"] == "ready"
            assert ready["revision"] == 1
            assert ready["html"] == raw.decode("utf-8")
            assert ready["size"] == len(raw)

            external = b"<html><body>external</body></html>"
            page_path.write_bytes(external)
            repaired = await get_project_dashboard_view(project_id="project-owner", db=session, user=user)
            assert repaired["state"] == "repair_required"
            assert repaired["revision"] == 1
            assert repaired["sha256"] == hashlib.sha256(external).hexdigest()
            assert repaired["html"] is None

            page_path.unlink()
            missing = await get_project_dashboard_view(project_id="project-owner", db=session, user=user)
            assert missing["state"] == "repair_required"
            assert missing["revision"] == 1
            assert missing["sha256"] is None
            assert missing["html"] is None

            outside = tmp_path / "outside.html"
            outside.write_bytes(b"<html>secret</html>")
            page_path.symlink_to(outside)
            symlinked = await get_project_dashboard_view(project_id="project-owner", db=session, user=user)
            assert symlinked["state"] == "repair_required"
            assert symlinked["revision"] == 1
            assert symlinked["sha256"] is None
            assert symlinked["html"] is None


async def test_page_read_back_rejects_unusable_page_bytes(tmp_path: Path, monkeypatch) -> None:
    """非 UTF-8 与超限页面不进入 ready，也不返回任何内容。"""
    workspace_root = tmp_path / "workspace"
    workdir_rel = "projects/p1"
    page_path = workspace_root / workdir_rel / "dashboard" / "index.html"
    page_path.parent.mkdir(parents=True)
    monkeypatch.setattr(workspace_filesystem_module, "user_workspace_dir", lambda _uid: workspace_root)

    async with _scoped_database("pytest_dashboard_bytes") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(manager.async_engine, project_id="project-owner", uid="uid-owner", workdir_path=workdir_rel)
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")

            page_path.write_bytes(b"\xff\xfe\x00")
            broken = await get_project_dashboard_view(project_id="project-owner", db=session, user=user)
            assert broken["state"] == "repair_required"
            assert broken["html"] is None

            page_path.unlink()
            page_path.write_bytes(b"a" * (MAX_PAGE_BYTES + 1))
            oversized = await get_project_dashboard_view(project_id="project-owner", db=session, user=user)
            assert oversized["state"] == "repair_required"
            assert oversized["sha256"] is None
            assert oversized["html"] is None
