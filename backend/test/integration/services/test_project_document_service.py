"""项目命名 JSON 文档用例的真实 PostgreSQL 集成测试。"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yuxi.services.project_document_service import (
    get_project_document_view,
    put_project_document_view,
)
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


async def test_document_versions_conflict_with_current_version() -> None:
    """创建、替换与冲突返回当前 version，不静默覆盖。"""
    async with _scoped_database("pytest_project_docs") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(manager.async_engine, project_id="project-owner", uid="uid-owner")
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            created = await put_project_document_view(
                project_id="project-owner",
                key="dashboard.config",
                expected_version=0,
                content={"layout": "cards"},
                db=session,
                user=user,
            )
            assert created["version"] == 1

            replaced = await put_project_document_view(
                project_id="project-owner",
                key="dashboard.config",
                expected_version=1,
                content={"layout": "list"},
                db=session,
                user=user,
            )
            assert replaced["version"] == 2

            read = await get_project_document_view(
                project_id="project-owner",
                key="dashboard.config",
                db=session,
                user=user,
            )
            assert read["version"] == 2
            assert read["content"] == {"layout": "list"}

            with pytest.raises(HTTPException) as stale:
                await put_project_document_view(
                    project_id="project-owner",
                    key="dashboard.config",
                    expected_version=1,
                    content={"layout": "stale"},
                    db=session,
                    user=user,
                )
            assert stale.value.status_code == 409
            assert stale.value.detail == {"code": "version_conflict", "current_version": 2}

            with pytest.raises(HTTPException) as duplicate_create:
                await put_project_document_view(
                    project_id="project-owner",
                    key="dashboard.config",
                    expected_version=0,
                    content={"layout": "again"},
                    db=session,
                    user=user,
                )
            assert duplicate_create.value.status_code == 409
            assert duplicate_create.value.detail["current_version"] == 2

            with pytest.raises(HTTPException) as missing_document:
                await put_project_document_view(
                    project_id="project-owner",
                    key="data.missing",
                    expected_version=3,
                    content={},
                    db=session,
                    user=user,
                )
            assert missing_document.value.status_code == 409
            assert missing_document.value.detail["current_version"] == 0


async def test_concurrent_create_keeps_single_version_one_row() -> None:
    """真实并发创建同一 key：advisory lock 让一方成功、一方 409，只有一行 version 1。"""
    async with _scoped_database("pytest_project_docs_race") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(manager.async_engine, project_id="project-owner", uid="uid-owner")

        async def create(session: AsyncSession) -> dict:
            user = await _load_user(session, "uid-owner")
            return await put_project_document_view(
                project_id="project-owner",
                key="dashboard.config",
                expected_version=0,
                content={"writer": id(session)},
                db=session,
                user=user,
            )

        async with sessions() as session_a, sessions() as session_b:
            outcomes = await asyncio.gather(create(session_a), create(session_b), return_exceptions=True)

        successes = [outcome for outcome in outcomes if isinstance(outcome, dict)]
        conflicts = [outcome for outcome in outcomes if isinstance(outcome, HTTPException)]
        assert len(successes) == 1
        assert len(conflicts) == 1
        assert conflicts[0].status_code == 409
        assert conflicts[0].detail["current_version"] == 1

        async with manager.async_engine.connect() as connection:
            count = await connection.scalar(
                text("SELECT count(*) FROM project_documents WHERE project_id = 'project-owner'")
            )
            version = await connection.scalar(
                text("SELECT version FROM project_documents WHERE project_id = 'project-owner'")
            )
        assert count == 1
        assert version == 1


async def test_document_requires_owned_selectable_project() -> None:
    """其他用户、隐式与已删除 Project 统一 404，不读取或写入文档。"""
    async with _scoped_database("pytest_project_docs_scope") as (manager, sessions):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_user(manager.async_engine, uid="uid-other")
        await _seed_project(manager.async_engine, project_id="project-owner", uid="uid-owner")
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

            with pytest.raises(HTTPException) as cross_user:
                await put_project_document_view(
                    project_id="project-owner",
                    key="dashboard.config",
                    expected_version=0,
                    content={},
                    db=session,
                    user=other,
                )
            assert cross_user.value.status_code == 404

            with pytest.raises(HTTPException) as implicit:
                await get_project_document_view(
                    project_id="project-implicit",
                    key="dashboard.config",
                    db=session,
                    user=owner,
                )
            assert implicit.value.status_code == 404

            with pytest.raises(HTTPException) as deleted:
                await put_project_document_view(
                    project_id="project-deleted",
                    key="dashboard.config",
                    expected_version=0,
                    content={},
                    db=session,
                    user=owner,
                )
            assert deleted.value.status_code == 404

        async with manager.async_engine.connect() as connection:
            count = await connection.scalar(text("SELECT count(*) FROM project_documents"))
        assert count == 0
