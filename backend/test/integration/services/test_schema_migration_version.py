"""Yuxi Schema 版本事实在真实 PostgreSQL 上的集成测试。"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.storage.postgres.manager import (
    BUSINESS_SCHEMA_VERSION,
    KNOWLEDGE_SCHEMA_VERSION,
    YUANLEI_SCHEMA_VERSION,
    PostgresManager,
)
from yuxi.storage.postgres.models_knowledge import KnowledgeBase

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

LEGACY_TASK_TABLE_SQL = """
CREATE TABLE tasks (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    progress DOUBLE PRECISION NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    payload JSONB,
    result JSONB,
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITHOUT TIME ZONE,
    completed_at TIMESTAMP WITHOUT TIME ZONE
)
"""


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


async def _create_isolated_manager(prefix: str):
    """创建位于独立 PostgreSQL Schema 的 manager 与清理句柄。"""
    schema = f"{prefix}_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    return schema, admin_engine, scoped_engine, _scoped_manager(scoped_engine)


async def _drop_isolated_schema(schema: str, admin_engine, scoped_engine) -> None:
    """释放隔离 Schema 及其 engine。"""
    await scoped_engine.dispose()
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await admin_engine.dispose()


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


async def test_v072_business_converges_current_schema_idempotently() -> None:
    """v0.7.2 发布结构一次补齐当前字段与约束，重复执行保持幂等。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_task_schema")

    try:
        await manager.create_business_tables()
        async with scoped_engine.begin() as connection:
            # v0.7.2 tag 没有这些字段，不能用当前 ORM 预建它们来证明迁移。
            for column in ("prepared_at", "first_output_at", "first_model_request_at"):
                await connection.execute(text(f"ALTER TABLE agent_runs DROP COLUMN {column}"))
            await connection.execute(text("ALTER TABLE agent_runs ADD COLUMN last_event_id VARCHAR(64)"))
            await connection.execute(text("DROP TABLE scheduled_agent_runs"))
            await connection.execute(text("DROP TABLE scheduled_agent_jobs"))
            await connection.execute(text("DROP TABLE tasks"))
            await connection.execute(text(LEGACY_TASK_TABLE_SQL))
            await connection.execute(
                text(
                    "INSERT INTO tasks (id, name, type, status) "
                    "VALUES ('legacy-running', 'legacy', 'knowledge_parse', 'running')"
                )
            )

        await manager.ensure_business_schema()
        await manager.ensure_business_schema()

        async with scoped_engine.connect() as connection:
            task_columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'tasks'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
            run_columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'agent_runs'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
            row = (
                await connection.execute(
                    text("SELECT status, error, handler_version, attempt_count FROM tasks WHERE id = 'legacy-running'")
                )
            ).one()
            scheduled_tables = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = :schema "
                            "AND table_name IN ('scheduled_agent_jobs', 'scheduled_agent_runs')"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
            scheduled_columns = {
                (row.table_name, row.column_name)
                for row in (
                    await connection.execute(
                        text(
                            "SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema "
                            "AND table_name IN ('scheduled_agent_jobs', 'scheduled_agent_runs')"
                        ),
                        {"schema": schema},
                    )
                )
            }
            scheduled_constraints = {
                row.conname: row.definition
                for row in (
                    await connection.execute(
                        text(
                            """
                            SELECT con.conname, pg_get_constraintdef(con.oid) AS definition
                            FROM pg_constraint AS con
                            JOIN pg_namespace AS ns ON ns.oid = con.connamespace
                            WHERE ns.nspname = :schema
                              AND con.conname IN (
                                  'fk_scheduled_agent_jobs_project_uid',
                                  'uq_scheduled_agent_jobs_uid_creation_request',
                                  'scheduled_agent_runs_job_id_fkey',
                                  'uq_scheduled_agent_runs_job_occurrence',
                                  'uq_scheduled_agent_runs_request',
                                  'uq_scheduled_agent_runs_thread'
                              )
                            """
                        ),
                        {"schema": schema},
                    )
                )
            }
            scheduled_indexes = set(
                (
                    await connection.execute(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE schemaname = :schema "
                            "AND tablename IN ('scheduled_agent_jobs', 'scheduled_agent_runs')"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )

        assert {
            "handler_version",
            "dedupe_key",
            "attempt_count",
            "worker_id",
            "heartbeat_at",
            "lease_expires_at",
            "timeout_seconds",
        } <= task_columns
        assert {"prepared_at", "first_output_at", "first_model_request_at"} <= run_columns
        assert "last_event_id" not in run_columns
        assert tuple(row) == ("running", None, 0, 0)
        assert scheduled_tables == {"scheduled_agent_jobs", "scheduled_agent_runs"}
        assert {
            ("scheduled_agent_jobs", "creation_request_id"),
            ("scheduled_agent_jobs", "creation_intent_hash"),
            ("scheduled_agent_jobs", "model_spec"),
            ("scheduled_agent_runs", "model_spec"),
        }.issubset(scheduled_columns)
        assert "ON DELETE CASCADE" in scheduled_constraints["fk_scheduled_agent_jobs_project_uid"]
        assert "ON DELETE CASCADE" in scheduled_constraints["scheduled_agent_runs_job_id_fkey"]
        assert (
            "UNIQUE (uid, creation_request_id)" in scheduled_constraints["uq_scheduled_agent_jobs_uid_creation_request"]
        )
        assert {
            "uq_scheduled_agent_runs_job_occurrence",
            "uq_scheduled_agent_runs_request",
            "uq_scheduled_agent_runs_thread",
        }.issubset(scheduled_constraints)
        assert {
            "ix_scheduled_agent_jobs_due",
            "ix_scheduled_agent_runs_job_created",
            "ix_scheduled_agent_runs_dispatching",
        }.issubset(scheduled_indexes)
        assert BUSINESS_SCHEMA_VERSION == 7
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_release_upgrade_adds_audit_columns_idempotently() -> None:
    """发布版缺失的 Trace 与 Message 审计列由完整升级补齐，且可安全重放。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_audit_schema")
    try:
        await manager.create_business_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("ALTER TABLE agent_runs DROP COLUMN langfuse_trace_id"))
            audit_columns = (
                "operation_id",
                "started_at",
                "finished_at",
                "duration_ms",
                "sequence",
                "execution_status",
                "usage",
            )
            for column in audit_columns:
                await connection.execute(text(f"ALTER TABLE messages DROP COLUMN {column}"))

        await manager.ensure_business_schema()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP INDEX uq_messages_run_role_operation_id"))
            await connection.execute(
                text(
                    "CREATE UNIQUE INDEX uq_messages_run_operation_id "
                    "ON messages(run_id, operation_id) WHERE operation_id IS NOT NULL"
                )
            )
        await manager.ensure_business_schema()

        async with scoped_engine.connect() as connection:
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name IN ('agent_runs', 'messages')"
                        ),
                        {"schema": schema},
                    )
                ).all()
            )
            audit_indexes = {
                name: definition
                for name, definition in (
                    await connection.execute(
                        text(
                            "SELECT indexname, indexdef FROM pg_indexes "
                            "WHERE schemaname = :schema AND tablename = 'messages' "
                            "AND indexname LIKE 'uq_messages_run%operation_id'"
                        ),
                        {"schema": schema},
                    )
                ).all()
            }
        assert ("agent_runs", "langfuse_trace_id") in columns
        assert {("messages", column) for column in audit_columns} <= columns
        assert "uq_messages_run_operation_id" not in audit_indexes
        assert "(run_id, role, operation_id)" in audit_indexes["uq_messages_run_role_operation_id"]
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_v1_to_v2_adds_file_attempt_owner_idempotently() -> None:
    """知识 schema 相邻升级为文件中间态增加 Task attempt fencing。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_knowledge_schema")
    try:
        async with scoped_engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE knowledge_files ("
                    "id SERIAL PRIMARY KEY, file_id VARCHAR(64) NOT NULL, status VARCHAR(32), "
                    "error_message TEXT, updated_at TIMESTAMPTZ)"
                )
            )
            await connection.execute(
                text("INSERT INTO knowledge_files (file_id, status) VALUES ('legacy-file', 'parsing')")
            )

        await manager.upgrade_knowledge_schema_v1_to_v2()
        await manager.upgrade_knowledge_schema_v1_to_v2()

        async with scoped_engine.connect() as connection:
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'knowledge_files'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
            legacy = (
                await connection.execute(
                    text("SELECT status, error_message FROM knowledge_files WHERE file_id = 'legacy-file'")
                )
            ).one()
        assert {"processing_task_id", "processing_owner"} <= columns
        assert tuple(legacy) == (
            "error_parsing",
            "service_interrupted: 旧执行实例中断，处理结果未知，请重试",
        )
        assert KNOWLEDGE_SCHEMA_VERSION == 2
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_timestamp_defaults_match_database_clock_in_non_utc_session() -> None:
    """带时区字段不依赖 PostgreSQL 会话时区解释无时区 UTC。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_knowledge_clock")
    try:
        await manager.create_knowledge_tables()
        session_factory = async_sessionmaker(scoped_engine, expire_on_commit=False)
        async with session_factory.begin() as session:
            await session.execute(text("SET TIME ZONE 'Asia/Shanghai'"))
            database = KnowledgeBase(kb_id="clock-kb", name="clock", kb_type="milvus")
            session.add(database)
            await session.flush()
            database_now = await session.scalar(text("SELECT clock_timestamp()"))

        async with session_factory() as verify_session:
            await verify_session.execute(text("SET TIME ZONE 'UTC'"))
            persisted_at = await verify_session.scalar(
                text("SELECT created_at FROM knowledge_bases WHERE kb_id = 'clock-kb'")
            )

        assert persisted_at.tzinfo is not None
        assert abs((persisted_at - database_now).total_seconds()) < 2
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_unversioned_knowledge_baseline_adds_timestamp_before_owner_convergence() -> None:
    """未版本化的旧表缺少 updated_at 时仍能收敛中间态。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_knowledge_baseline")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO knowledge_bases (kb_id, name, kb_type) VALUES ('legacy-kb', 'legacy', 'milvus')")
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_files (file_id, kb_id, filename, status) "
                    "VALUES ('legacy-file', 'legacy-kb', 'legacy.txt', 'indexing')"
                )
            )
            await connection.execute(text("ALTER TABLE knowledge_files DROP COLUMN processing_task_id"))
            await connection.execute(text("ALTER TABLE knowledge_files DROP COLUMN processing_owner"))
            await connection.execute(text("ALTER TABLE knowledge_files DROP COLUMN updated_at"))

        await manager.create_knowledge_tables()
        await manager.ensure_knowledge_schema()

        async with scoped_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT status, error_message, updated_at, processing_task_id, processing_owner "
                        "FROM knowledge_files WHERE file_id = 'legacy-file'"
                    )
                )
            ).one()
        assert row.status == "error_indexing"
        assert row.error_message == "service_interrupted: 旧执行实例中断，处理结果未知，请重试"
        assert row.updated_at is not None
        assert row.processing_task_id is None
        assert row.processing_owner is None
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_unversioned_baseline_repairs_existing_legacy_task_table() -> None:
    """未版本化数据库的 create_all + ensure 路径必须补齐旧 tasks 表。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_task_baseline")

    try:
        await manager.create_business_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP TABLE tasks"))
            await connection.execute(text(LEGACY_TASK_TABLE_SQL))
            await connection.execute(
                text(
                    "INSERT INTO tasks (id, name, type, status) "
                    "VALUES ('legacy-pending', 'legacy', 'knowledge_parse', 'pending')"
                )
            )

        await manager.ensure_business_schema()

        async with scoped_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT status, error, handler_version, lease_expires_at FROM tasks WHERE id = 'legacy-pending'"
                    )
                )
            ).one()
        assert tuple(row) == ("pending", None, 0, None)
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_schema_version_is_persisted_and_runtime_validation_fails_closed() -> None:
    """版本表缺失、错误和正确三种状态必须形成精确启动结论。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_schema_version")

    try:
        with pytest.raises(RuntimeError, match="business=missing"):
            await manager.require_current_schema()

        await manager.create_schema_version_table()
        await manager.record_schema_version("business", BUSINESS_SCHEMA_VERSION + 1)
        with pytest.raises(RuntimeError, match=f"business={BUSINESS_SCHEMA_VERSION + 1}"):
            await manager.require_current_schema()

        await manager.record_schema_version("business", BUSINESS_SCHEMA_VERSION)
        with pytest.raises(RuntimeError, match="knowledge=missing"):
            await manager.require_current_schema()

        await manager.record_schema_version("knowledge", KNOWLEDGE_SCHEMA_VERSION)
        with pytest.raises(RuntimeError, match="yuanlei=missing"):
            await manager.require_current_schema()

        await manager.record_schema_version("yuanlei", YUANLEI_SCHEMA_VERSION)
        await manager.require_current_schema()
        assert await manager.get_schema_versions() == {
            "business": BUSINESS_SCHEMA_VERSION,
            "knowledge": KNOWLEDGE_SCHEMA_VERSION,
            "yuanlei": YUANLEI_SCHEMA_VERSION,
        }
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


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


async def test_yuanlei_v2_to_v3_converges_project_agents_idempotently() -> None:
    """真实 PostgreSQL 从缺少 project_agents 的 yuanlei v2 形态幂等收敛到 v3。"""
    schema = f"pytest_project_agents_{uuid.uuid4().hex[:16]}"
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
            await connection.execute(text("DROP TABLE project_agents"))

        await manager.upgrade_yuanlei_schema_v2_to_v3()
        await manager.upgrade_yuanlei_schema_v2_to_v3()

        async with scoped_engine.connect() as connection:
            table_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = current_schema() AND table_name = 'project_agents'"
                )
            )
            assert table_count == 1
            constraint_names = {
                row.conname
                for row in (
                    await connection.execute(
                        text(
                            """
                            SELECT con.conname
                            FROM pg_constraint AS con
                            JOIN pg_namespace AS ns ON ns.oid = con.connamespace
                            WHERE ns.nspname = current_schema()
                              AND con.conrelid = 'project_agents'::regclass
                            """
                        )
                    )
                )
            }
            assert {
                "fk_project_agents_project_id",
                "fk_project_agents_agent_slug",
                "uq_project_agents_project_agent",
            }.issubset(constraint_names)
    finally:
        if scoped_engine is not None:
            await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def test_yuanlei_v3_to_v4_converges_agent_sandboxes_idempotently() -> None:
    """真实 PostgreSQL 从缺少专属沙盒表的 yuanlei v3 形态幂等收敛到 v4。"""
    schema = f"pytest_agent_sandboxes_{uuid.uuid4().hex[:16]}"
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
            await connection.execute(text("DROP TABLE IF EXISTS agent_sandbox_events"))
            await connection.execute(text("DROP TABLE IF EXISTS agent_sandboxes"))

        await manager.upgrade_yuanlei_schema_v3_to_v4()
        await manager.upgrade_yuanlei_schema_v3_to_v4()

        async with scoped_engine.connect() as connection:
            table_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = current_schema() "
                    "AND table_name IN ('agent_sandboxes', 'agent_sandbox_events')"
                )
            )
            assert table_count == 2
            constraint_names = {
                row.conname
                for row in (
                    await connection.execute(
                        text(
                            """
                            SELECT con.conname
                            FROM pg_constraint AS con
                            JOIN pg_namespace AS ns ON ns.oid = con.connamespace
                            WHERE ns.nspname = current_schema()
                              AND con.conrelid = 'agent_sandboxes'::regclass
                            """
                        )
                    )
                )
            }
            assert {
                "fk_agent_sandboxes_uid_users",
                "fk_agent_sandboxes_agent_slug",
                "fk_agent_sandboxes_project_id",
                "uq_agent_sandboxes_owner",
                "uq_agent_sandboxes_scope_key",
                "uq_agent_sandboxes_sandbox_id",
            }.issubset(constraint_names)
    finally:
        if scoped_engine is not None:
            await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def test_yuanlei_v4_to_v5_converges_coding_credentials_idempotently() -> None:
    """真实 PostgreSQL 从缺少编码凭据表的 yuanlei v4 形态幂等收敛到 v5。"""
    schema = f"pytest_coding_credentials_{uuid.uuid4().hex[:16]}"
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
            await connection.execute(text("DROP TABLE IF EXISTS coding_credentials"))

        await manager.upgrade_yuanlei_schema_v4_to_v5()
        await manager.upgrade_yuanlei_schema_v4_to_v5()

        async with scoped_engine.connect() as connection:
            table_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = current_schema() AND table_name = 'coding_credentials'"
                )
            )
            assert table_count == 1
            unique_indexes = {
                row.indexname
                for row in (
                    await connection.execute(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE schemaname = current_schema() AND tablename = 'coding_credentials' "
                            "AND indexname IN ('uq_coding_credentials_user', 'uq_coding_credentials_global')"
                        )
                    )
                )
            }
            assert unique_indexes == {"uq_coding_credentials_user", "uq_coding_credentials_global"}
    finally:
        if scoped_engine is not None:
            await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def test_yuanlei_v5_to_v6_converges_coding_sessions_idempotently() -> None:
    """真实 PostgreSQL 从缺少会话三表的 yuanlei v5 形态幂等收敛到 v6。"""
    schema = f"pytest_coding_sessions_{uuid.uuid4().hex[:16]}"
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
            await connection.execute(text("DROP TABLE IF EXISTS coding_session_events"))
            await connection.execute(text("DROP TABLE IF EXISTS coding_session_turns"))
            await connection.execute(text("DROP TABLE IF EXISTS coding_sessions"))

        await manager.upgrade_yuanlei_schema_v5_to_v6()
        await manager.upgrade_yuanlei_schema_v5_to_v6()

        async with scoped_engine.connect() as connection:
            table_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = current_schema() "
                    "AND table_name IN ('coding_sessions', 'coding_session_turns', 'coding_session_events')"
                )
            )
            assert table_count == 3
            constraint_names = {
                row.conname
                for row in (
                    await connection.execute(
                        text(
                            "SELECT con.conname FROM pg_constraint AS con "
                            "JOIN pg_namespace AS ns ON ns.oid = con.connamespace "
                            "WHERE ns.nspname = current_schema() "
                            "AND con.conname IN ('uq_coding_session_turns_seq', 'uq_coding_session_events_seq', "
                            "'fk_coding_sessions_uid_users', 'fk_coding_sessions_project_id')"
                        )
                    )
                )
            }
            assert constraint_names == {
                "uq_coding_session_turns_seq",
                "uq_coding_session_events_seq",
                "fk_coding_sessions_uid_users",
                "fk_coding_sessions_project_id",
            }
    finally:
        if scoped_engine is not None:
            await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def test_yuanlei_v6_to_v7_adds_reference_columns_and_dedupes_idempotently() -> None:
    """真实 PostgreSQL：v6→v7 补齐引用列，并把同执行器多行收敛为最近一条。"""
    schema = f"pytest_coding_reference_{uuid.uuid4().hex[:16]}"
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
        # 退回 v6 形态：移除引用列后预置同执行器多行 active（global scope 避免用户外键）。
        async with scoped_engine.begin() as connection:
            await connection.execute(
                text(
                    "ALTER TABLE coding_credentials "
                    "DROP COLUMN IF EXISTS source, "
                    "DROP COLUMN IF EXISTS model_provider_id, "
                    "DROP COLUMN IF EXISTS key_mode"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO coding_credentials "
                    "(id, scope, uid, executor, provider, status, version, updated_at, created_at, "
                    " api_key_cipher, extra_json) "
                    "VALUES "
                    "('g1', 'global', NULL, 'opencode', 'provider-a', 'active', 1, "
                    " NOW() - INTERVAL '2 hours', NOW() - INTERVAL '3 hours', decode('00', 'hex'), '{}'::jsonb), "
                    "('g2', 'global', NULL, 'opencode', 'provider-b', 'active', 1, "
                    " NOW(), NOW() - INTERVAL '1 hour', NULL, '{}'::jsonb), "
                    "('g3', 'global', NULL, 'codex', 'provider-a', 'active', 1, NOW(), NOW(), NULL, '{}'::jsonb)"
                )
            )

        await manager.upgrade_yuanlei_schema_v6_to_v7()
        await manager.upgrade_yuanlei_schema_v6_to_v7()

        async with scoped_engine.connect() as connection:
            columns = {
                row.column_name
                for row in (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() AND table_name = 'coding_credentials' "
                            "AND column_name IN ('source', 'model_provider_id', 'key_mode')"
                        )
                    )
                )
            }
            assert columns == {"source", "model_provider_id", "key_mode"}
            source_default = await connection.scalar(
                text("SELECT source FROM coding_credentials WHERE id = 'g2'")
            )
            assert source_default == "manual"
            rows = (
                await connection.execute(
                    text(
                        "SELECT id, executor, status, api_key_cipher FROM coding_credentials "
                        "ORDER BY id"
                    )
                )
            ).all()
            assert {(row.executor, row.status) for row in rows} == {
                ("opencode", "active"),
                ("opencode", "deleted"),
                ("codex", "active"),
            }
            active_by_executor: dict[str, str] = {}
            for row in rows:
                if row.status == "active":
                    active_by_executor[row.executor] = row.id
            assert active_by_executor == {"opencode": "g2", "codex": "g3"}
            deleted_row = next(row for row in rows if row.id == "g1")
            assert deleted_row.api_key_cipher is None
    finally:
        if scoped_engine is not None:
            await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def test_business_runtime_scope_width_widens_idempotently_for_dedicated_agents() -> None:
    """存量 business 库把 Run / Git worktree 的 runtime_scope_id 扩到 191（幂等）。"""
    schema = f"pytest_runtime_scope_{uuid.uuid4().hex[:16]}"
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
                text("ALTER TABLE agent_runs ALTER COLUMN runtime_scope_id TYPE VARCHAR(64)")
            )
            await connection.execute(
                text("ALTER TABLE project_git_worktrees ALTER COLUMN runtime_scope_id TYPE VARCHAR(64)")
            )

        await manager.ensure_runtime_scope_width()
        await manager.ensure_runtime_scope_width()

        async with scoped_engine.connect() as connection:
            widths = {
                row.table_name: row.character_maximum_length
                for row in (
                    await connection.execute(
                        text(
                            "SELECT table_name, character_maximum_length "
                            "FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND column_name = 'runtime_scope_id' "
                            "AND table_name IN ('agent_runs', 'project_git_worktrees')"
                        )
                    )
                )
            }
            assert widths == {"agent_runs": 191, "project_git_worktrees": 191}
    finally:
        if scoped_engine is not None:
            await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def test_project_agents_enforce_project_agent_boundaries() -> None:
    """真实 PostgreSQL 拒绝悬空绑定与重复绑定。"""
    schema = f"pytest_project_agent_bounds_{uuid.uuid4().hex[:16]}"
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
                    "VALUES ('owner', 'uid-owner', 'x', 'user', 0, 0)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO projects (id, uid, name, selection_status, workdir_path, directory_mode) VALUES "
                    "('project-owner', 'uid-owner', 'Owner', 'selectable', 'projects/owner', 'linked')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO agents (slug, backend_id, name, pics, config_json, share_config, "
                    "is_default, is_subagent) "
                    "VALUES ('employee', 'ChatbotAgent', '员工', '[]'::jsonb, '{}'::jsonb, '{}'::jsonb, FALSE, FALSE)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO project_agents (id, project_id, agent_slug, config_overrides) "
                    "VALUES ('binding-1', 'project-owner', 'employee', '{}'::jsonb)"
                )
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO project_agents (id, project_id, agent_slug, config_overrides) "
                            "VALUES ('binding-2', 'project-owner', 'employee', '{}'::jsonb)"
                        )
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO project_agents (id, project_id, agent_slug, config_overrides) "
                            "VALUES ('binding-3', 'missing-project', 'employee', '{}'::jsonb)"
                        )
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO project_agents (id, project_id, agent_slug, config_overrides) "
                            "VALUES ('binding-4', 'project-owner', 'missing-agent', '{}'::jsonb)"
                        )
                    )
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
