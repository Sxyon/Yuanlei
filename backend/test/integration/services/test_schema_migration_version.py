"""Yuxi Schema 版本事实在真实 PostgreSQL 上的集成测试。"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from yuxi.storage.postgres.manager import BUSINESS_SCHEMA_VERSION, PostgresManager

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """本文件自行创建隔离 Schema，不依赖运行中的 API。"""


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


async def test_schema_migration_lock_serializes_real_postgres_sessions() -> None:
    """两个 migrator 竞争同一 advisory lock 时只允许一个进入临界区。"""
    engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    manager = _scoped_manager(engine)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first_migrator() -> None:
        async with manager.schema_migration_lock():
            first_entered.set()
            await release_first.wait()

    async def second_migrator() -> None:
        await first_entered.wait()
        async with manager.schema_migration_lock():
            second_entered.set()

    first_task = asyncio.create_task(first_migrator())
    second_task = asyncio.create_task(second_migrator())
    try:
        await asyncio.wait_for(first_entered.wait(), timeout=2)
        await asyncio.sleep(0.1)
        assert second_entered.is_set() is False
        release_first.set()
        await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=2)
        assert second_entered.is_set() is True
    finally:
        release_first.set()
        for task in (first_task, second_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(first_task, second_task, return_exceptions=True)
        await engine.dispose()


async def test_schema_version_is_persisted_and_runtime_validation_fails_closed() -> None:
    """版本表缺失、错误和正确三种状态必须形成精确启动结论。"""
    schema = f"pytest_schema_version_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    scoped_engine = None

    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

        scoped_engine = create_async_engine(
            os.environ["POSTGRES_URL"],
            pool_pre_ping=True,
            connect_args={"server_settings": {"search_path": schema}},
        )
        manager = _scoped_manager(scoped_engine)

        with pytest.raises(RuntimeError, match="business=missing"):
            await manager.require_current_schema(include_knowledge=False)

        await manager.create_schema_version_table()
        await manager.record_schema_version("business", BUSINESS_SCHEMA_VERSION + 1)
        with pytest.raises(RuntimeError, match=f"business={BUSINESS_SCHEMA_VERSION + 1}"):
            await manager.require_current_schema(include_knowledge=False)

        await manager.record_schema_version("business", BUSINESS_SCHEMA_VERSION)
        await manager.require_current_schema(include_knowledge=False)
        assert await manager.get_schema_versions() == {"business": BUSINESS_SCHEMA_VERSION}
    finally:
        if scoped_engine is not None:
            await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def test_business_v2_converges_project_git_schema() -> None:
    """真实 PostgreSQL 从缺少 Git 表的 v2 形态幂等收敛到 v3。"""
    schema = f"pytest_git_schema_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    scoped_engine = None
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped_engine = create_async_engine(
            os.environ["POSTGRES_URL"],
            pool_pre_ping=True,
            connect_args={"server_settings": {"search_path": schema}},
        )
        manager = _scoped_manager(scoped_engine)
        await manager.create_business_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP TABLE project_git_worktrees"))
            await connection.execute(text("DROP TABLE project_git_repositories"))
            await connection.execute(text("DROP TABLE git_connections"))
            await connection.execute(text("DROP TABLE git_credentials"))

        await manager.ensure_business_schema()
        await manager.ensure_business_schema()

        async with scoped_engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema() AND table_name LIKE '%git%'"
                )
            )
            assert {row.table_name for row in rows} >= {
                "git_credentials",
                "git_connections",
                "project_git_repositories",
                "project_git_worktrees",
            }
            alias_index = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_indexes WHERE schemaname = current_schema() "
                    "AND indexname = 'uq_project_git_repositories_project_lower_alias'"
                )
            )
            assert alias_index == 1
    finally:
        if scoped_engine is not None:
            await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def test_project_git_schema_enforces_alias_and_user_boundaries() -> None:
    """真实 PostgreSQL 拒绝大小写 alias 冲突和跨用户复合外键。"""
    schema = f"pytest_git_constraints_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    scoped_engine = None
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped_engine = create_async_engine(
            os.environ["POSTGRES_URL"],
            pool_pre_ping=True,
            connect_args={"server_settings": {"search_path": schema}},
        )
        manager = _scoped_manager(scoped_engine)
        await manager.create_business_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (username, uid, password_hash, role, login_failed_count, is_deleted) "
                    "VALUES ('user-a', 'uid-a', 'x', 'user', 0, 0), ('user-b', 'uid-b', 'x', 'user', 0, 0)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO projects (id, uid, name, selection_status, workdir_path, directory_mode) VALUES "
                    "('project-a', 'uid-a', 'A', 'selectable', 'projects/a', 'managed'), "
                    "('project-b', 'uid-b', 'B', 'selectable', 'projects/b', 'managed')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO git_credentials (id, uid, purpose, ciphertext, nonce, key_version) VALUES "
                    "('token-a', 'uid-a', 'gitea_api_token', '\\x01', '\\x02', 1), "
                    "('token-b', 'uid-b', 'gitea_api_token', '\\x01', '\\x02', 1), "
                    "('key-a', 'uid-a', 'deploy_private_key', '\\x01', '\\x02', 1)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO git_connections "
                    "(id, uid, name, provider, api_origin, ssh_host, ssh_port, ssh_known_host_key, "
                    "api_token_credential_id, idempotency_key) VALUES "
                    "('connection-a', 'uid-a', 'A', 'gitea', 'https://a.invalid', 'a.invalid', 22, 'host-a', "
                    "'token-a', 'request-a'), "
                    "('connection-b', 'uid-b', 'B', 'gitea', 'https://b.invalid', 'b.invalid', 22, 'host-b', "
                    "'token-b', 'request-b')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO project_git_repositories "
                    "(id, project_id, uid, connection_id, alias, directory_name, repository_owner, repository_name, "
                    "deploy_public_key, deploy_public_key_fingerprint, deploy_private_credential_id, idempotency_key) "
                    "VALUES ('repo-a', 'project-a', 'uid-a', 'connection-a', 'API', 'api-safe', 'owner', 'repo', "
                    "'public', 'fingerprint', 'key-a', 'bind-a')"
                )
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO project_git_repositories "
                            "(id, project_id, uid, connection_id, alias, directory_name, repository_owner, "
                            "repository_name, deploy_public_key, deploy_public_key_fingerprint, "
                            "deploy_private_credential_id, idempotency_key) VALUES "
                            "('repo-alias-conflict', 'project-a', 'uid-a', 'connection-a', 'api', 'api-other', "
                            "'owner', 'other', 'public', 'fingerprint', 'key-a', 'bind-b')"
                        )
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO project_git_repositories "
                            "(id, project_id, uid, connection_id, alias, directory_name, repository_owner, "
                            "repository_name, deploy_public_key, deploy_public_key_fingerprint, "
                            "deploy_private_credential_id, idempotency_key) VALUES "
                            "('repo-cross-user', 'project-a', 'uid-a', 'connection-b', 'web', 'web-safe', "
                            "'owner', 'web', 'public', 'fingerprint', 'key-a', 'bind-c')"
                        )
                    )
    finally:
        if scoped_engine is not None:
            await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
