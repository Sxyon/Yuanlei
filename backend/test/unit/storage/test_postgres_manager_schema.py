from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from yuxi.storage.postgres.manager import (
    BUSINESS_SCHEMA_VERSION,
    KNOWLEDGE_SCHEMA_VERSION,
    YUANLEI_SCHEMA_VERSION,
    BusinessBase,
    KnowledgeBase,
    PostgresManager,
)
from yuxi.storage.postgres.models_business import AgentRun


def test_business_and_knowledge_metadata_are_disjoint():
    """业务与知识域 metadata 保持独立，迁移器分别创建两个域。"""

    assert BusinessBase is not KnowledgeBase
    assert "users" in BusinessBase.metadata.tables
    assert "knowledge_bases" not in BusinessBase.metadata.tables
    assert "evaluation_runs" not in BusinessBase.metadata.tables
    assert "knowledge_bases" in KnowledgeBase.metadata.tables
    assert "evaluation_runs" in KnowledgeBase.metadata.tables
    assert "users" not in KnowledgeBase.metadata.tables


@pytest.mark.asyncio
async def test_require_current_schema_rejects_missing_or_incompatible_domains(monkeypatch):
    manager = PostgresManager()

    monkeypatch.setattr(manager, "get_schema_versions", lambda: _async_value({}))
    with pytest.raises(RuntimeError, match=r"business=missing .*knowledge=missing"):
        await manager.require_current_schema()

    monkeypatch.setattr(manager, "get_schema_versions", lambda: _async_value({"business": 99}))
    with pytest.raises(RuntimeError, match=r"business=99"):
        await manager.require_current_schema()

    monkeypatch.setattr(
        manager,
        "get_schema_versions",
        lambda: _async_value(
            {
                "business": BUSINESS_SCHEMA_VERSION,
                "knowledge": KNOWLEDGE_SCHEMA_VERSION,
                "yuanlei": YUANLEI_SCHEMA_VERSION,
            }
        ),
    )
    await manager.require_current_schema()


async def _async_value(value):
    return value


def test_project_uid_foreign_key_has_schema_convergence_name():
    """ORM fresh schema 必须与后续收敛 SQL 使用同一 FK 名称。"""
    projects = BusinessBase.metadata.tables["projects"]

    assert [constraint.name for constraint in projects.foreign_key_constraints] == ["fk_projects_uid_users"]


def test_project_lifecycle_columns_and_constraint_are_in_fresh_schema():
    """Fresh schema 与升级收敛必须共享 Project 软删除契约。"""
    projects = BusinessBase.metadata.tables["projects"]

    assert projects.c.status.nullable is False
    assert "deleted_at" in projects.c
    assert "ck_projects_status" in {constraint.name for constraint in projects.constraints}


def test_project_git_schema_owns_user_bound_foreign_keys_and_alias_index():
    """Fresh schema 在数据库层拒绝跨用户绑定并约束大小写 alias。"""
    assert {
        "git_credentials",
        "git_connections",
        "project_git_repositories",
        "project_git_worktrees",
    }.issubset(BusinessBase.metadata.tables)
    repositories = BusinessBase.metadata.tables["project_git_repositories"]
    assert {
        "fk_project_git_repositories_project_uid",
        "fk_project_git_repositories_connection_uid",
        "fk_project_git_repositories_credential_uid",
    }.issubset({constraint.name for constraint in repositories.foreign_key_constraints})
    assert "uq_project_git_repositories_project_lower_alias" in {
        index.name for index in repositories.indexes
    }


def test_agent_run_serialization_does_not_project_removed_redis_cursor():
    """AgentRun 序列化不再暴露已删除的 Redis 游标字段。"""
    run = AgentRun(
        id="run-1",
        conversation_thread_id="thread-1",
        runtime_scope_id="thread-1",
        agent_slug="main",
        uid="user-1",
        request_id="request-1",
        input_payload={},
    )

    assert "last_event_id" not in AgentRun.__table__.c
    assert "last_event_id" not in run.to_dict()


class _RecordingConnection:
    def __init__(self):
        self.statements: list[str] = []

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))


class _RecordingBegin:
    def __init__(self, connection: _RecordingConnection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _RecordingEngine:
    def __init__(self, connection: _RecordingConnection):
        self.connection = connection

    def begin(self):
        return _RecordingBegin(self.connection)


@asynccontextmanager
async def _recording_manager():
    manager = PostgresManager()
    original_initialized = manager._initialized
    original_engine = manager.async_engine
    connection = _RecordingConnection()

    manager._initialized = True
    manager.async_engine = _RecordingEngine(connection)
    try:
        yield manager, connection
    finally:
        manager._initialized = original_initialized
        manager.async_engine = original_engine


@pytest.mark.asyncio
async def test_ensure_business_schema_backfills_subagent_thread_columns_before_dropping_legacy_columns():
    async with _recording_manager() as (manager, connection):
        await manager.ensure_business_schema()

    statements = "\n".join(connection.statements)

    assert "SET agent_slug = agent_id" in statements
    assert "SET conversation_thread_id = thread_id" in statements
    assert "SET created_by_run_id = COALESCE(parent_agent_run_id, parent_run_id)" in statements
    assert "SET subagent_slug = c.agent_id" in statements
    assert "SET created_by_run_id = created_by_parent_run_id::VARCHAR" in statements
    assert "ALTER COLUMN subagent_slug SET NOT NULL" in statements
    assert "ALTER COLUMN created_by_run_id SET NOT NULL" in statements
    assert statements.index("SET agent_slug = agent_id") < statements.index("DROP COLUMN IF EXISTS agent_id")
    assert statements.index("SET conversation_thread_id = thread_id") < statements.index(
        "DROP COLUMN IF EXISTS thread_id"
    )
    assert statements.index("COALESCE(parent_agent_run_id, parent_run_id)") < statements.index(
        "DROP COLUMN IF EXISTS parent_agent_run_id"
    )
    assert statements.index("created_by_parent_run_id") < statements.index(
        "DROP COLUMN IF EXISTS created_by_parent_run_id"
    )
    assert "ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'" in statements
    assert "ADD COLUMN IF NOT EXISTS deleted_at" in statements
    assert "ADD CONSTRAINT ck_projects_status" in statements


@pytest.mark.asyncio
async def test_release_upgrade_converges_run_timing_and_removes_cursor():
    """发布版升级使用同一套完整 DDL，包含全部模型前时间且删除旧游标。"""
    async with _recording_manager() as (manager, connection):
        await manager.ensure_business_schema()

    for column in ("prepared_at", "first_output_at", "first_model_request_at"):
        assert (
            f"ALTER TABLE IF EXISTS agent_runs ADD COLUMN IF NOT EXISTS {column} TIMESTAMP WITHOUT TIME ZONE"
            in connection.statements
        )
    assert "ALTER TABLE IF EXISTS agent_runs DROP COLUMN IF EXISTS last_event_id" in connection.statements


@pytest.mark.asyncio
async def test_yuanlei_v1_to_v2_upgrade_backfills_legacy_allocations_before_constraints():
    """Project Git v1 行必须保留并回填 legacy 语义后才收紧约束。"""
    async with _recording_manager() as (manager, connection):
        await manager.upgrade_yuanlei_schema_v1_to_v2()

    statements = "\n".join(connection.statements)
    assert "SET selection_source = 'legacy'" in statements
    assert "SET branch_kind = 'legacy'" in statements
    assert "ALTER COLUMN base_sha DROP NOT NULL" in statements
    assert "'requested', 'preparing', 'ready'" in statements
    assert statements.index("SET branch_kind = 'legacy'") < statements.index(
        "ALTER COLUMN branch_kind SET NOT NULL"
    )


def test_project_agent_schema_owns_project_and_agent_foreign_keys():
    """Fresh schema 在数据库层拒绝悬空的项目/智能体绑定并保证单项目单绑定。"""
    assert "project_agents" in BusinessBase.metadata.tables
    table = BusinessBase.metadata.tables["project_agents"]
    foreign_keys = {constraint.name for constraint in table.foreign_key_constraints}
    assert foreign_keys == {"fk_project_agents_project_id", "fk_project_agents_agent_slug"}
    assert "uq_project_agents_project_agent" in {constraint.name for constraint in table.constraints}
    assert {"ix_project_agents_project_id", "ix_project_agents_agent_slug"}.issubset(
        {index.name for index in table.indexes}
    )


@pytest.mark.asyncio
async def test_yuanlei_v2_to_v3_upgrade_creates_project_agents_idempotently():
    """项目数字员工表由 yuanlei 域升级收敛，重放不重复建表。"""
    async with _recording_manager() as (manager, connection):
        await manager.upgrade_yuanlei_schema_v2_to_v3()
        await manager.upgrade_yuanlei_schema_v2_to_v3()

    statements = "\n".join(connection.statements)
    assert "CREATE TABLE IF NOT EXISTS project_agents" in statements
    assert "REFERENCES projects(id) ON DELETE CASCADE" in statements
    assert "REFERENCES agents(slug) ON DELETE CASCADE" in statements
    assert "UNIQUE (project_id, agent_slug)" in statements
    assert "CREATE INDEX IF NOT EXISTS ix_project_agents_project_id" in statements
    assert "CREATE INDEX IF NOT EXISTS ix_project_agents_agent_slug" in statements


def test_agent_sandbox_schema_owns_owner_foreign_keys_and_uniques():
    """专属沙盒表在数据库层拒绝悬空归属并保证每 (uid, agent, project) 单条记录。"""
    assert "agent_sandboxes" in BusinessBase.metadata.tables
    table = BusinessBase.metadata.tables["agent_sandboxes"]
    foreign_keys = {constraint.name for constraint in table.foreign_key_constraints}
    assert foreign_keys == {
        "fk_agent_sandboxes_uid_users",
        "fk_agent_sandboxes_agent_slug",
        "fk_agent_sandboxes_project_id",
    }
    constraint_names = {constraint.name for constraint in table.constraints}
    assert {
        "uq_agent_sandboxes_owner",
        "uq_agent_sandboxes_scope_key",
        "uq_agent_sandboxes_sandbox_id",
    }.issubset(constraint_names)
    assert "ix_agent_sandboxes_status" in {index.name for index in table.indexes}

    events = BusinessBase.metadata.tables["agent_sandbox_events"]
    assert "ix_agent_sandbox_events_sandbox_created" in {index.name for index in events.indexes}


@pytest.mark.asyncio
async def test_yuanlei_v3_to_v4_upgrade_creates_agent_sandboxes_idempotently():
    """专属沙盒表由 yuanlei 域升级收敛，重放不重复建表。"""
    async with _recording_manager() as (manager, connection):
        await manager.upgrade_yuanlei_schema_v3_to_v4()
        await manager.upgrade_yuanlei_schema_v3_to_v4()

    statements = "\n".join(connection.statements)
    assert "CREATE TABLE IF NOT EXISTS agent_sandboxes" in statements
    assert "REFERENCES users(uid) ON DELETE CASCADE" in statements
    assert "REFERENCES agents(slug) ON DELETE CASCADE" in statements
    assert "REFERENCES projects(id) ON DELETE CASCADE" in statements
    assert "UNIQUE (uid, agent_slug, project_id)" in statements
    assert "UNIQUE (scope_key)" in statements
    assert "UNIQUE (sandbox_id)" in statements
    assert "CREATE INDEX IF NOT EXISTS ix_agent_sandboxes_status" in statements
    assert "CREATE TABLE IF NOT EXISTS agent_sandbox_events" in statements
    assert "ix_agent_sandbox_events_sandbox_created" in statements


@pytest.mark.asyncio
async def test_ensure_business_schema_cleans_duplicate_active_agent_runs_before_unique_index():
    async with _recording_manager() as (manager, connection):
        await manager.ensure_business_schema()

    statements = "\n".join(connection.statements)

    assert "WITH duplicated_active_runs AS" in statements
    assert "active_run_migration_conflict" in statements
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_one_active_per_thread" in statements
    assert statements.index("WITH duplicated_active_runs AS") < statements.index(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_one_active_per_thread"
    )


@pytest.mark.asyncio
async def test_ensure_business_schema_backfills_unviewed_marker_for_no_run_threads():
    """没有 chat/resume Run 的历史会话要写入未读哨兵，确保回填探测条件收敛为 false。"""
    async with _recording_manager() as (manager, connection):
        await manager.ensure_business_schema()

    statements = "\n".join(connection.statements)

    assert "SELECT EXISTS (SELECT 1 FROM conversations WHERE last_viewed_run_id IS NULL)" in statements
    assert "SET last_viewed_run_id = r.run_id" in statements
    assert "SET last_viewed_run_id = :marker WHERE last_viewed_run_id IS NULL" in statements
    assert statements.index("SET last_viewed_run_id = r.run_id") < statements.index(
        "SET last_viewed_run_id = :marker WHERE last_viewed_run_id IS NULL"
    )


@pytest.mark.asyncio
async def test_ensure_business_schema_creates_user_config_table():
    async with _recording_manager() as (manager, connection):
        await manager.ensure_business_schema()

    statements = "\n".join(connection.statements)

    assert "CREATE TABLE IF NOT EXISTS user_config" in statements
    assert "enable_memory BOOLEAN NOT NULL DEFAULT FALSE" in statements


@pytest.mark.asyncio
async def test_ensure_business_schema_creates_generic_config_options_table():
    async with _recording_manager() as (manager, connection):
        await manager.ensure_business_schema()

    statements = "\n".join(connection.statements)

    assert "CREATE TABLE IF NOT EXISTS config_options" in statements
    assert "params JSONB NOT NULL" in statements
    assert "value JSONB NOT NULL" in statements
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ix_config_options_key" in statements


@pytest.mark.asyncio
async def test_ensure_business_schema_adds_run_origin_snapshot_columns():
    async with _recording_manager() as (manager, connection):
        await manager.ensure_business_schema()

    statements = "\n".join(connection.statements)
    assert "agent_runs ADD COLUMN IF NOT EXISTS source VARCHAR(32)" in statements
    assert "agent_runs ADD COLUMN IF NOT EXISTS channel VARCHAR(32)" in statements
    assert "agent_runs ADD COLUMN IF NOT EXISTS external_id VARCHAR(128)" in statements
    assert "agent_runs ADD COLUMN IF NOT EXISTS origin_metadata JSONB" in statements
    assert "agent_run_requests ADD COLUMN IF NOT EXISTS channel VARCHAR(32)" in statements
    assert "agent_run_requests ADD COLUMN IF NOT EXISTS external_id VARCHAR(128)" in statements
    assert "agent_run_requests ADD COLUMN IF NOT EXISTS origin_metadata JSONB" in statements


@pytest.mark.asyncio
async def test_ensure_business_schema_adds_idempotent_agent_run_lease_columns_and_index():
    async with _recording_manager() as (manager, connection):
        await manager.ensure_business_schema()

    statements = "\n".join(connection.statements)
    assert "agent_runs ADD COLUMN IF NOT EXISTS worker_id VARCHAR(128)" in statements
    assert "agent_runs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP WITHOUT TIME ZONE" in statements
    assert "agent_runs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP WITHOUT TIME ZONE" in statements
    assert "CREATE INDEX IF NOT EXISTS ix_agent_runs_status_lease_expires" in statements


@pytest.mark.asyncio
async def test_ensure_business_schema_adds_nonterminal_run_shape_constraint_without_scanning_history():
    async with _recording_manager() as (manager, connection):
        await manager.ensure_business_schema()

    statements = "\n".join(connection.statements)
    assert "ck_agent_runs_nonterminal_shape" in statements
    assert "run_type = 'resume'" in statements
    assert "run_type = 'subagent'" in statements
    assert "NOT VALID" in statements
    assert "EXCEPTION WHEN duplicate_object" in statements


@pytest.mark.asyncio
async def test_ensure_business_schema_removes_unbound_api_keys_before_requiring_user_id():
    async with _recording_manager() as (manager, connection):
        await manager.ensure_business_schema()

    statements = "\n".join(connection.statements)

    assert "UPDATE cli_auth_sessions" in statements
    assert "DELETE FROM api_keys WHERE user_id IS NULL" in statements
    assert "ALTER TABLE IF EXISTS api_keys ALTER COLUMN user_id SET NOT NULL" in statements
    assert statements.index("UPDATE cli_auth_sessions") < statements.index("DELETE FROM api_keys WHERE user_id IS NULL")
    assert statements.index("DELETE FROM api_keys WHERE user_id IS NULL") < statements.index(
        "ALTER TABLE IF EXISTS api_keys ALTER COLUMN user_id SET NOT NULL"
    )
    assert "ALTER TABLE IF EXISTS api_keys ADD COLUMN IF NOT EXISTS request_id VARCHAR(64)" in statements
    assert "ALTER TABLE IF EXISTS api_keys ADD COLUMN IF NOT EXISTS intent_hash VARCHAR(64)" in statements
    assert (
        "ALTER TABLE IF EXISTS api_keys ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMP WITHOUT TIME ZONE" in statements
    )
    assert "users.is_deleted <> 0" in statements
    assert "COALESCE(api_key.revoked_at, users.deleted_at, CURRENT_TIMESTAMP)" in statements
    assert statements.index("ADD COLUMN IF NOT EXISTS revoked_at") < statements.index("users.is_deleted <> 0")
    assert statements.index("users.is_deleted <> 0") < statements.index(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_api_keys_request_id"
    )
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ix_api_keys_request_id" in statements
    assert "CREATE INDEX IF NOT EXISTS ix_api_keys_revoked_at" in statements


@pytest.mark.asyncio
async def test_share_config_migration_wraps_legacy_scopes_as_read_only():
    """Agent/skill 迁移只把旧 scope 写入 read_scope，manage_scope 置空，避免把历史只读/使用权限追溯升级为 MANAGE。"""
    async with _recording_manager() as (manager, connection):
        await manager.ensure_business_schema()
        await manager.ensure_knowledge_schema()

    statements = "\n".join(connection.statements)
    assert "UPDATE agents SET share_config = jsonb_build_object" in statements
    assert "UPDATE skills SET share_config = jsonb_build_object" in statements
    assert "UPDATE knowledge_bases SET share_config = jsonb_build_object" in statements
    assert "'read_scope'" in statements
    assert "'manage_scope', NULL" in statements
    assert "ALTER TABLE IF EXISTS agents ALTER COLUMN share_config TYPE JSONB USING share_config::jsonb" in statements
    assert "ALTER TABLE IF EXISTS skills ALTER COLUMN share_config TYPE JSONB USING share_config::jsonb" in statements
    assert statements.index(
        "ALTER TABLE IF EXISTS agents ALTER COLUMN share_config TYPE JSONB USING share_config::jsonb"
    ) < statements.index("UPDATE agents SET share_config = jsonb_build_object")
    assert statements.index(
        "ALTER TABLE IF EXISTS skills ALTER COLUMN share_config TYPE JSONB USING share_config::jsonb"
    ) < statements.index("UPDATE skills SET share_config = jsonb_build_object")
    assert "ALTER TABLE IF EXISTS agents ALTER COLUMN share_config DROP DEFAULT" in statements
    assert "ALTER TABLE IF EXISTS skills ALTER COLUMN share_config DROP DEFAULT" in statements


@pytest.mark.asyncio
async def test_ensure_knowledge_schema_rebuilds_vectors_for_incomplete_legacy_chunks():
    async with _recording_manager() as (manager, connection):
        await manager.ensure_knowledge_schema()

    statements = "\n".join(connection.statements)

    assert (
        "UPDATE knowledge_chunks SET graph_structure_indexed = TRUE "
        "WHERE graph_indexed IS TRUE AND graph_structure_indexed IS NOT TRUE"
    ) in statements
    assert "mention.entity_id = entity.entity_id AND chunk.graph_indexed IS NOT TRUE" in statements
    assert "mention.triple_id = triple.triple_id AND chunk.graph_indexed IS NOT TRUE" in statements
    assert "THEN 'pending' ELSE 'indexed'" in statements
