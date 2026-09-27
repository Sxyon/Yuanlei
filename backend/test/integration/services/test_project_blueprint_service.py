"""项目蓝图用例的真实 PostgreSQL 与真实文件系统集成测试。"""

from __future__ import annotations

import os
import errno
import uuid
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from pathlib import Path

import pytest
import yuxi.workspace.filesystem as workspace_filesystem
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yuxi.services.project_blueprint_service import (
    archive_project_blueprint_view,
    create_project_blueprint_view,
    get_project_blueprint_archive_view,
    get_project_blueprint_view,
    list_project_blueprint_archives_view,
    list_project_blueprint_view,
    put_project_blueprint_view,
)
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import User
from yuxi.workspace.paths import ensure_user_workspace, user_workspace_dir
from yuxi.workspace.workdir import Workdir
from server.routers.project_blueprint_router import project_blueprints
from server.utils.auth_middleware import get_db, get_required_user

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
    selection_status: str = "selectable",
    status: str = "active",
    workdir_path: str = "projects/owner",
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO projects (id, uid, name, selection_status, workdir_path, directory_mode, status) "
                "VALUES (:project_id, :uid, 'Pytest', :selection_status, :workdir_path, 'linked', :status)"
            ),
            {
                "project_id": project_id,
                "uid": uid,
                "selection_status": selection_status,
                "workdir_path": workdir_path,
                "status": status,
            },
        )


async def _load_user(session: AsyncSession, uid: str) -> User:
    user = await session.scalar(select(User).where(User.uid == uid))
    assert user is not None
    return user


def _create_linked_workdir(uid: str, workdir_path: str) -> Path:
    """在真实 UserWorkspace 中物化一个 linked Workdir。"""
    ensure_user_workspace(uid)
    host = user_workspace_dir(uid).joinpath(*PurePosixPath(workdir_path).parts)
    host.mkdir(parents=True, exist_ok=True)
    return host


async def test_blueprint_round_trip_is_filesystem_owned(monkeypatch, tmp_path) -> None:
    """写入落到 Workdir 文件；绕过 service 直接改文件会被后续读取回读。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    workdir_path = "projects/owner"
    host_workdir = _create_linked_workdir("uid-owner", workdir_path)
    blueprint_file = host_workdir / ".yuanlei" / "blueprint" / "product-vision.md"

    async with _scoped_database("pytest_blueprint_rt") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(
            manager.async_engine, project_id="project-owner", uid="uid-owner", workdir_path=workdir_path
        )
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")

            empty = await list_project_blueprint_view(project_id="project-owner", db=session, user=user)
            assert empty["directory"] == ".yuanlei/blueprint"
            assert empty["documents"] == []

            created = await put_project_blueprint_view(
                project_id="project-owner",
                name="product-vision.md",
                content="# 愿景\n",
                db=session,
                user=user,
            )
            assert created["size"] == len("# 愿景\n".encode())
            assert blueprint_file.read_text(encoding="utf-8") == "# 愿景\n"

            listed = await list_project_blueprint_view(project_id="project-owner", db=session, user=user)
            assert [document["name"] for document in listed["documents"]] == ["product-vision.md"]

            # 绕过 service 直接改文件，读取回读文件本身，证明 Workdir 是事实 Owner。
            blueprint_file.write_text("# 改版\n", encoding="utf-8")
            read = await get_project_blueprint_view(
                project_id="project-owner", name="product-vision.md", db=session, user=user
            )
            assert read["content"] == "# 改版\n"
            assert read["size"] == len("# 改版\n".encode())

            await put_project_blueprint_view(
                project_id="project-owner",
                name="product-vision.md",
                content="# v2\n",
                db=session,
                user=user,
            )
            assert blueprint_file.read_text(encoding="utf-8") == "# v2\n"


async def test_blueprint_create_and_archive_preserve_history_without_overwrite(monkeypatch, tmp_path) -> None:
    """新建同名文件拒绝覆盖；归档移走当前文件并保留可回读正文。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    host_workdir = _create_linked_workdir("uid-owner", "projects/owner")
    async with _scoped_database("pytest_blueprint_archive") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(
            manager.async_engine,
            project_id="project-owner",
            uid="uid-owner",
        )
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            first = await create_project_blueprint_view(
                project_id="project-owner",
                name="plan.md",
                content="# 第一版\n",
                db=session,
                user=user,
            )
            assert first["content"] == "# 第一版\n"
            with pytest.raises(HTTPException) as duplicate:
                await create_project_blueprint_view(
                    project_id="project-owner",
                    name="plan.md",
                    content="# 意外覆盖\n",
                    db=session,
                    user=user,
                )
            assert duplicate.value.status_code == 409
            assert (host_workdir / ".yuanlei/blueprint/plan.md").read_text() == "# 第一版\n"

            archived = await archive_project_blueprint_view(
                project_id="project-owner",
                name="plan.md",
                db=session,
                user=user,
            )
            assert not (host_workdir / ".yuanlei/blueprint/plan.md").exists()
            assert (host_workdir / ".yuanlei/blueprint/archive" / archived["archive_name"]).read_text() == "# 第一版\n"
            history = await list_project_blueprint_archives_view(
                project_id="project-owner",
                db=session,
                user=user,
            )
            assert [entry["archive_name"] for entry in history["documents"]] == [archived["archive_name"]]
            read = await get_project_blueprint_archive_view(
                project_id="project-owner",
                archive_name=archived["archive_name"],
                db=session,
                user=user,
            )
            assert read["content"] == "# 第一版\n"
            assert (
                await list_project_blueprint_view(
                    project_id="project-owner",
                    db=session,
                    user=user,
                )
            )["documents"] == []
            with pytest.raises(HTTPException) as missing:
                await get_project_blueprint_view(project_id="project-owner", name="plan.md", db=session, user=user)
            assert missing.value.status_code == 404

            recreated = await create_project_blueprint_view(
                project_id="project-owner",
                name="plan.md",
                content="# 第二版\n",
                db=session,
                user=user,
            )
            assert recreated["content"] == "# 第二版\n"
            assert read["content"] == "# 第一版\n"

            for code in (errno.ENOTSUP, errno.EINVAL):

                def unsupported_move(*_args):
                    raise OSError(code, "unsupported")

                with monkeypatch.context() as patch:
                    patch.setattr(workspace_filesystem, "_rename_noreplace", unsupported_move)
                    with pytest.raises(HTTPException) as unavailable:
                        await archive_project_blueprint_view(
                            project_id="project-owner", name="plan.md", db=session, user=user
                        )
                assert unavailable.value.status_code == 409
                assert unavailable.value.detail["code"] == "blueprint_archive_unavailable"
                assert (host_workdir / ".yuanlei/blueprint/plan.md").read_text() == "# 第二版\n"


async def test_archive_move_preserves_concurrent_files(monkeypatch, tmp_path) -> None:
    """目标抢占不能被覆盖，原子移动只取当时的源且不删除新写入。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    host = _create_linked_workdir("uid-owner", "projects/owner")
    source = host / "plan.md"
    target = host / "archive.md"
    source.write_text("# 原文件\n", encoding="utf-8")
    workdir = Workdir.open_existing("uid-owner", "projects/owner")
    original_rename = workspace_filesystem._rename_noreplace

    def race_target(*args):
        target.write_text("# 已有历史\n", encoding="utf-8")
        return original_rename(*args)

    with monkeypatch.context() as patch:
        patch.setattr(workspace_filesystem, "_rename_noreplace", race_target)
        with pytest.raises(FileExistsError):
            workdir.move_file("/plan.md", "/archive.md")
    assert source.read_text(encoding="utf-8") == "# 原文件\n"
    assert target.read_text(encoding="utf-8") == "# 已有历史\n"

    target.unlink()

    def race_source(*args):
        replacement = host / "replacement.md"
        replacement.write_text("# 替换文件\n", encoding="utf-8")
        os.replace(replacement, source)
        return original_rename(*args)

    with monkeypatch.context() as patch:
        patch.setattr(workspace_filesystem, "_rename_noreplace", race_source)
        workdir.move_file("/plan.md", "/archive.md")
    assert not source.exists()
    assert target.read_text(encoding="utf-8") == "# 替换文件\n"

    target.unlink()
    source.write_text("# 待归档\n", encoding="utf-8")

    original_stat = os.stat

    def recreate_source_after_move(path, *args, **kwargs):
        if path == "archive.md" and kwargs.get("dir_fd") is not None:
            source.write_text("# 并发新版本\n", encoding="utf-8")
        return original_stat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "stat", recreate_source_after_move)
        workdir.move_file("/plan.md", "/archive.md")
    assert source.read_text(encoding="utf-8") == "# 并发新版本\n"
    assert target.read_text(encoding="utf-8") == "# 待归档\n"


async def test_blueprint_http_create_archive_history_and_authorization(monkeypatch, tmp_path) -> None:
    """真实 HTTP 路由连接 PostgreSQL 与 Workdir，越权读取和归档返回 404。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    _create_linked_workdir("uid-owner", "projects/owner")
    async with _scoped_database("pytest_blueprint_http") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_user(manager.async_engine, uid="uid-other")
        await _seed_project(manager.async_engine, project_id="project-owner", uid="uid-owner")
        async with sessions() as session:
            current = {"user": await _load_user(session, "uid-owner")}
            app = FastAPI()
            app.include_router(project_blueprints, prefix="/api")

            async def provide_db():
                yield session

            async def provide_user():
                return current["user"]

            app.dependency_overrides[get_db] = provide_db
            app.dependency_overrides[get_required_user] = provide_user
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                base = "/api/projects/project-owner/blueprint"
                created = await client.post(base, json={"name": "plan.md", "content": "# 初版\n"})
                assert created.status_code == 201, created.text
                duplicate = await client.post(base, json={"name": "plan.md", "content": "# 覆盖\n"})
                assert duplicate.status_code == 409, duplicate.text
                assert (await client.get(f"{base}/plan.md")).json()["content"] == "# 初版\n"

                current["user"] = await _load_user(session, "uid-other")
                assert (await client.get(f"{base}/history")).status_code == 404
                assert (await client.post(f"{base}/plan.md/archive")).status_code == 404
                current["user"] = await _load_user(session, "uid-owner")

                archived = await client.post(f"{base}/plan.md/archive")
                assert archived.status_code == 200, archived.text
                archive_name = archived.json()["archive_name"]
                history = await client.get(f"{base}/history")
                assert history.status_code == 200, history.text
                assert history.json()["documents"][0]["archive_name"] == archive_name
                read = await client.get(f"{base}/history/{archive_name}")
                assert read.status_code == 200, read.text
                assert read.json()["content"] == "# 初版\n"
                assert (await client.get(f"{base}/plan.md")).status_code == 404
                current["user"] = await _load_user(session, "uid-other")
                assert (await client.get(f"{base}/history/{archive_name}")).status_code == 404


async def test_blueprint_lists_only_markdown_documents(monkeypatch, tmp_path) -> None:
    """蓝图目录内的非 Markdown 文件与子目录不进入文档列表。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    workdir_path = "projects/owner"
    host_workdir = _create_linked_workdir("uid-owner", workdir_path)
    blueprint_dir = host_workdir / ".yuanlei" / "blueprint"
    blueprint_dir.mkdir(parents=True)
    (blueprint_dir / "design.md").write_text("# Design\n", encoding="utf-8")
    (blueprint_dir / "notes.txt").write_text("noise", encoding="utf-8")
    (blueprint_dir / "nested").mkdir()

    async with _scoped_database("pytest_blueprint_list") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(
            manager.async_engine, project_id="project-owner", uid="uid-owner", workdir_path=workdir_path
        )
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            listed = await list_project_blueprint_view(project_id="project-owner", db=session, user=user)
            assert [document["name"] for document in listed["documents"]] == ["design.md"]


async def test_blueprint_rejects_path_escape_and_bad_names(monkeypatch, tmp_path) -> None:
    """越界或非法文档名在进入文件系统前被拒，且不产生文件。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    workdir_path = "projects/owner"
    host_workdir = _create_linked_workdir("uid-owner", workdir_path)

    async with _scoped_database("pytest_blueprint_names") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(
            manager.async_engine, project_id="project-owner", uid="uid-owner", workdir_path=workdir_path
        )
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            for bad_name in ("../escape.md", "sub/escape.md", "Escape.md", "escape.txt"):
                with pytest.raises(ValueError):
                    await put_project_blueprint_view(
                        project_id="project-owner",
                        name=bad_name,
                        content="x",
                        db=session,
                        user=user,
                    )
            assert not (host_workdir / "escape.md").exists()
            assert not (host_workdir / ".yuanlei" / "escape.md").exists()


async def test_blueprint_conflicts_when_directory_is_file(monkeypatch, tmp_path) -> None:
    """`.yuanlei` 被普通文件占用时显式 409，不写入蓝图。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    workdir_path = "projects/owner"
    host_workdir = _create_linked_workdir("uid-owner", workdir_path)
    (host_workdir / ".yuanlei").write_text("occupied", encoding="utf-8")

    async with _scoped_database("pytest_blueprint_conflict") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(
            manager.async_engine, project_id="project-owner", uid="uid-owner", workdir_path=workdir_path
        )
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            with pytest.raises(HTTPException) as conflict:
                await put_project_blueprint_view(
                    project_id="project-owner",
                    name="product-vision.md",
                    content="# v\n",
                    db=session,
                    user=user,
                )
            assert conflict.value.status_code == 409
            assert conflict.value.detail["code"] == "blueprint_directory_conflict"

            with pytest.raises(HTTPException) as list_conflict:
                await list_project_blueprint_view(project_id="project-owner", db=session, user=user)
            assert list_conflict.value.status_code == 409


async def test_blueprint_requires_owned_selectable_project(monkeypatch, tmp_path) -> None:
    """其他用户、隐式与已删除 Project 统一 404，且不写入文件。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    workdir_path = "projects/owner"
    _create_linked_workdir("uid-owner", workdir_path)

    async with _scoped_database("pytest_blueprint_scope") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_user(manager.async_engine, uid="uid-other")
        await _seed_project(
            manager.async_engine, project_id="project-owner", uid="uid-owner", workdir_path=workdir_path
        )
        await _seed_project(
            manager.async_engine,
            project_id="project-implicit",
            uid="uid-owner",
            selection_status="implicit",
        )
        await _seed_project(
            manager.async_engine,
            project_id="project-deleted",
            uid="uid-owner",
            status="deleted",
        )
        async with sessions() as session:
            owner = await _load_user(session, "uid-owner")
            other = await _load_user(session, "uid-other")

            for project_id in ("project-owner", "project-implicit", "project-deleted"):
                with pytest.raises(HTTPException) as denied:
                    await list_project_blueprint_view(project_id=project_id, db=session, user=other)
                assert denied.value.status_code == 404

            for project_id in ("project-implicit", "project-deleted"):
                with pytest.raises(HTTPException) as denied:
                    await put_project_blueprint_view(
                        project_id=project_id,
                        name="product-vision.md",
                        content="# v\n",
                        db=session,
                        user=owner,
                    )
                assert denied.value.status_code == 404


async def test_blueprint_missing_document_returns_404(monkeypatch, tmp_path) -> None:
    """目录存在但文档缺失时返回 404。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    workdir_path = "projects/owner"
    _create_linked_workdir("uid-owner", workdir_path)

    async with _scoped_database("pytest_blueprint_missing") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(
            manager.async_engine, project_id="project-owner", uid="uid-owner", workdir_path=workdir_path
        )
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            with pytest.raises(HTTPException) as missing:
                await get_project_blueprint_view(project_id="project-owner", name="missing.md", db=session, user=user)
            assert missing.value.status_code == 404
