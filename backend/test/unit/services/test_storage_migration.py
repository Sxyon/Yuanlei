from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from yuxi import storage_migration
from yuxi.storage_migrations.v071_workdirs import (
    V071ConversationBinding,
    V071WorkdirBinding,
    V071WorkdirMigrationPlan,
)


class _Session:
    def __init__(self, calls: list[object] | None = None):
        self.calls = calls

    async def execute(self, statement):
        if self.calls is not None:
            self.calls.append(("execute", str(statement)))

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_storage_migration_reads_legacy_schema_before_cutover(monkeypatch):
    calls: list[object] = []
    sessions = [_Session(), _Session(), _Session(calls), _Session()]

    @asynccontextmanager
    async def session_context():
        yield sessions.pop(0)

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value({}),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        create_business_tables=lambda: _record(calls, "create_business_tables"),
        create_knowledge_tables=lambda: _record(calls, "create_knowledge_tables"),
        ensure_business_schema=lambda: _record(calls, "ensure_business_schema"),
        ensure_knowledge_schema=lambda: _record(calls, "ensure_knowledge_schema"),
        setup_langgraph_checkpointer=lambda: _record(calls, "setup_langgraph_checkpointer"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    workdirs = (V071WorkdirBinding("workdir-1", "user-1"),)
    conversations = (V071ConversationBinding("thread-1", "user-1", "workdir-1"),)

    async def read_bindings(_db):
        calls.append("read_v071_workdir_plan")
        return V071WorkdirMigrationPlan(True, workdirs, conversations)

    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(storage_migration, "read_v071_workdir_plan", read_bindings)
    monkeypatch.setattr(storage_migration, "_require_quiescence_proof", lambda: calls.append("proof"))
    monkeypatch.setattr(
        storage_migration,
        "_converge_database_state",
        lambda *, fail_nonterminal_runs: _record(calls, f"converge:{fail_nonterminal_runs}"),
    )
    monkeypatch.setattr(
        storage_migration,
        "import_v071_workdirs",
        lambda actual_workdirs, actual_conversations: calls.append(("import", actual_workdirs, actual_conversations)),
    )
    monkeypatch.setattr(storage_migration, "rewrite_v071_workdir_paths", lambda _db: _record(calls, "rewrite"))
    monkeypatch.setattr(storage_migration, "verify_workdir_bindings", lambda _db: _record(calls, "verify"))
    monkeypatch.setattr(
        storage_migration,
        "cleanup_v071_thread_sources",
        lambda actual_conversations: calls.append(("cleanup", actual_conversations)),
    )
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", lambda _db: _record(calls, "skills"))
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: calls.append("mark_skills"))
    monkeypatch.setattr(storage_migration, "_ensure_yuanlei_schema", lambda: _record(calls, "yuanlei_schema"))
    monkeypatch.setattr(
        storage_migration,
        "migrate_runtime_storage_identity",
        lambda: calls.append("runtime_identity"),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: True)

    await storage_migration.main()

    assert calls.index("read_v071_workdir_plan") < calls.index("ensure_business_schema")
    assert calls.index("proof") < calls.index(("import", workdirs, conversations))
    assert calls.index(("import", workdirs, conversations)) < calls.index("ensure_business_schema")
    assert calls.index("verify") < calls.index(("cleanup", conversations))
    assert calls.index("mark_skills") < calls.index("runtime_identity")
    assert calls[-1] == "close"


@pytest.mark.asyncio
async def test_storage_migration_rejects_v071_schema_without_quiescence_proof(monkeypatch, tmp_path):
    calls: list[str] = []

    @asynccontextmanager
    async def session_context():
        yield _Session()

    manager = SimpleNamespace(
        initialize=lambda: None,
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value({}),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        create_business_tables=lambda: _record(calls, "create"),
        create_knowledge_tables=lambda: _record(calls, "create_knowledge"),
        ensure_business_schema=lambda: _record(calls, "schema"),
        ensure_knowledge_schema=lambda: _record(calls, "knowledge_schema"),
        setup_langgraph_checkpointer=lambda: _record(calls, "checkpoint"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(True, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setenv("YUXI_STORAGE_MIGRATION_QUIESCENCE_FILE", str(tmp_path / "missing"))
    monkeypatch.delenv("YUXI_STORAGE_MIGRATION_QUIESCENCE_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="migrate-storage.sh"):
        await storage_migration.main()

    assert calls == ["schema_lock", "close"]


@pytest.mark.asyncio
async def test_current_schema_skips_schema_ddl(monkeypatch):
    calls: list[str] = []
    sessions = [_Session(), _Session(), _Session()]

    @asynccontextmanager
    async def session_context():
        yield sessions.pop(0)

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value(
            {
                "business": storage_migration.BUSINESS_SCHEMA_VERSION,
                "knowledge": storage_migration.KNOWLEDGE_SCHEMA_VERSION,
                "yuanlei": storage_migration.YUANLEI_SCHEMA_VERSION,
            }
        ),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        create_business_tables=lambda: _record(calls, "create_business"),
        create_knowledge_tables=lambda: _record(calls, "create_knowledge"),
        ensure_business_schema=lambda: _record(calls, "business_schema"),
        ensure_knowledge_schema=lambda: _record(calls, "knowledge_schema"),
        setup_langgraph_checkpointer=lambda: _record(calls, "checkpoint"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(False, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setattr(
        storage_migration,
        "_converge_database_state",
        lambda *, fail_nonterminal_runs: _record(calls, f"converge:{fail_nonterminal_runs}"),
    )
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", lambda _db: _record(calls, "skills"))
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: calls.append("mark_skills"))
    monkeypatch.setattr(storage_migration, "migrate_runtime_storage_identity", lambda: calls.append("runtime_identity"))

    await storage_migration.main()

    assert {
        "create_business",
        "create_knowledge",
        "business_schema",
        "knowledge_schema",
        "checkpoint",
        f"version:business:{storage_migration.BUSINESS_SCHEMA_VERSION}",
        f"version:knowledge:{storage_migration.KNOWLEDGE_SCHEMA_VERSION}",
    }.isdisjoint(calls)
    assert "converge:False" in calls


@pytest.mark.asyncio
async def test_yuanlei_v1_is_upgraded_and_versioned_only_after_success(monkeypatch):
    calls: list[str] = []
    sessions = [_Session(), _Session(), _Session()]

    @asynccontextmanager
    async def session_context():
        yield sessions.pop(0)

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value(
            {
                "business": storage_migration.BUSINESS_SCHEMA_VERSION,
                "knowledge": storage_migration.KNOWLEDGE_SCHEMA_VERSION,
                "yuanlei": 1,
            }
        ),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        upgrade_yuanlei_schema_v1_to_v2=lambda: _record(calls, "upgrade_yuanlei_v1_v2"),
        upgrade_yuanlei_schema_v2_to_v3=lambda: _record(calls, "upgrade_yuanlei_v2_v3"),
        upgrade_yuanlei_schema_v3_to_v4=lambda: _record(calls, "upgrade_yuanlei_v3_v4"),
        upgrade_yuanlei_schema_v4_to_v5=lambda: _record(calls, "upgrade_yuanlei_v4_v5"),
        upgrade_yuanlei_schema_v5_to_v6=lambda: _record(calls, "upgrade_yuanlei_v5_v6"),
        upgrade_yuanlei_schema_v6_to_v7=lambda: _record(calls, "upgrade_yuanlei_v6_v7"),
        upgrade_yuanlei_schema_v7_to_v8=lambda: _record(calls, "upgrade_yuanlei_v7_v8"),
        upgrade_yuanlei_schema_v8_to_v9=lambda: _record(calls, "upgrade_yuanlei_v8_v9"),
        upgrade_yuanlei_schema_v9_to_v10=lambda: _record(calls, "upgrade_yuanlei_v9_v10"),
        upgrade_yuanlei_schema_v10_to_v11=lambda: _record(calls, "upgrade_yuanlei_v10_v11"),
        upgrade_yuanlei_schema_v11_to_v12=lambda: _record(calls, "upgrade_yuanlei_v11_v12"),
        upgrade_yuanlei_schema_v12_to_v13=lambda: _record(calls, "upgrade_yuanlei_v12_v13"),
        upgrade_yuanlei_schema_v13_to_v14=lambda: _record(calls, "upgrade_yuanlei_v13_v14"),
        upgrade_yuanlei_schema_v14_to_v15=lambda: _record(calls, "upgrade_yuanlei_v14_v15"),
        upgrade_yuanlei_schema_v15_to_v16=lambda: _record(calls, "upgrade_yuanlei_v15_v16"),
        upgrade_yuanlei_schema_v16_to_v17=lambda: _record(calls, "upgrade_yuanlei_v16_v17"),
        upgrade_yuanlei_schema_v17_to_v18=lambda: _record(calls, "upgrade_yuanlei_v17_v18"),
        upgrade_yuanlei_schema_v18_to_v19=lambda: _record(calls, "upgrade_yuanlei_v18_v19"),
        upgrade_yuanlei_schema_v19_to_v20=lambda: _record(calls, "upgrade_yuanlei_v19_v20"),
        upgrade_yuanlei_schema_v20_to_v21=lambda: _record(calls, "upgrade_yuanlei_v20_v21"),
        upgrade_yuanlei_schema_v21_to_v22=lambda: _record(calls, "upgrade_yuanlei_v21_v22"),
        upgrade_yuanlei_schema_v22_to_v23=lambda: _record(calls, "upgrade_yuanlei_v22_v23"),
        upgrade_yuanlei_schema_v23_to_v24=lambda: _record(calls, "upgrade_yuanlei_v23_v24"),
        upgrade_yuanlei_schema_v24_to_v25=lambda: _record(calls, "upgrade_yuanlei_v24_v25"),
        upgrade_yuanlei_schema_v25_to_v26=lambda: _record(calls, "upgrade_yuanlei_v25_v26"),
        upgrade_yuanlei_schema_v26_to_v27=lambda: _record(calls, "upgrade_yuanlei_v26_v27"),
        upgrade_yuanlei_schema_v27_to_v28=lambda: _record(calls, "upgrade_yuanlei_v27_v28"),
        upgrade_yuanlei_schema_v28_to_v29=lambda: _record(calls, "upgrade_yuanlei_v28_v29"),
        upgrade_yuanlei_schema_v29_to_v30=lambda: _record(calls, "upgrade_yuanlei_v29_v30"),
        upgrade_yuanlei_schema_v30_to_v31=lambda: _record(calls, "upgrade_yuanlei_v30_v31"),
        upgrade_yuanlei_schema_v31_to_v32=lambda: _record(calls, "upgrade_yuanlei_v31_v32"),
        upgrade_yuanlei_schema_v32_to_v33=lambda: _record(calls, "work_results"),
        upgrade_yuanlei_schema_v33_to_v34=lambda: _record(calls, "work_context"),
        upgrade_yuanlei_schema_v34_to_v35=lambda: _record(calls, "execution_results"),
        upgrade_yuanlei_schema_v35_to_v36=lambda: _record(calls, "topic_followup"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(False, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setattr(
        storage_migration,
        "_converge_database_state",
        lambda *, fail_nonterminal_runs: _record(calls, f"converge:{fail_nonterminal_runs}"),
    )
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", lambda _db: _record(calls, "skills"))
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: calls.append("mark_skills"))
    monkeypatch.setattr(storage_migration, "migrate_runtime_storage_identity", lambda: calls.append("runtime_identity"))

    await storage_migration.main()

    version_call = f"version:yuanlei:{storage_migration.YUANLEI_SCHEMA_VERSION}"
    assert calls.index("upgrade_yuanlei_v1_v2") < calls.index("upgrade_yuanlei_v2_v3")
    assert calls.index("upgrade_yuanlei_v2_v3") < calls.index("upgrade_yuanlei_v3_v4")
    assert calls.index("upgrade_yuanlei_v3_v4") < calls.index("upgrade_yuanlei_v4_v5")
    assert calls.index("upgrade_yuanlei_v4_v5") < calls.index("upgrade_yuanlei_v5_v6")
    assert calls.index("upgrade_yuanlei_v5_v6") < calls.index("upgrade_yuanlei_v6_v7")
    assert calls.index("upgrade_yuanlei_v6_v7") < calls.index("upgrade_yuanlei_v7_v8")
    assert calls.index("upgrade_yuanlei_v7_v8") < calls.index("upgrade_yuanlei_v8_v9")
    assert calls.index("upgrade_yuanlei_v8_v9") < calls.index("upgrade_yuanlei_v9_v10")
    assert calls.index("upgrade_yuanlei_v9_v10") < calls.index("upgrade_yuanlei_v10_v11")
    assert calls.index("upgrade_yuanlei_v10_v11") < calls.index("upgrade_yuanlei_v11_v12")
    assert calls.index("upgrade_yuanlei_v11_v12") < calls.index("upgrade_yuanlei_v12_v13")
    assert calls.index("upgrade_yuanlei_v12_v13") < calls.index("upgrade_yuanlei_v13_v14")
    assert calls.index("upgrade_yuanlei_v13_v14") < calls.index("upgrade_yuanlei_v14_v15")
    assert calls.index("upgrade_yuanlei_v14_v15") < calls.index("upgrade_yuanlei_v15_v16")
    assert calls.index("upgrade_yuanlei_v15_v16") < calls.index("upgrade_yuanlei_v16_v17")
    assert calls.index("upgrade_yuanlei_v16_v17") < calls.index("upgrade_yuanlei_v17_v18")
    assert calls.index("upgrade_yuanlei_v17_v18") < calls.index("upgrade_yuanlei_v18_v19")
    assert calls.index("upgrade_yuanlei_v18_v19") < calls.index("upgrade_yuanlei_v19_v20")
    assert calls.index("upgrade_yuanlei_v19_v20") < calls.index("upgrade_yuanlei_v20_v21")
    assert calls.index("upgrade_yuanlei_v20_v21") < calls.index("upgrade_yuanlei_v21_v22")
    assert calls.index("upgrade_yuanlei_v21_v22") < calls.index("upgrade_yuanlei_v22_v23")
    assert calls.index("upgrade_yuanlei_v22_v23") < calls.index("upgrade_yuanlei_v23_v24")
    assert calls.index("upgrade_yuanlei_v23_v24") < calls.index("upgrade_yuanlei_v24_v25")
    assert calls.index("upgrade_yuanlei_v24_v25") < calls.index("upgrade_yuanlei_v27_v28")
    assert calls.index("upgrade_yuanlei_v27_v28") < calls.index("upgrade_yuanlei_v28_v29") < calls.index("upgrade_yuanlei_v29_v30") < calls.index("upgrade_yuanlei_v30_v31") < calls.index(version_call)


@pytest.mark.asyncio
async def test_yuanlei_v2_is_upgraded_to_project_agents_without_replaying_v1(monkeypatch):
    calls: list[str] = []
    sessions = [_Session(), _Session(), _Session()]

    @asynccontextmanager
    async def session_context():
        yield sessions.pop(0)

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value(
            {
                "business": storage_migration.BUSINESS_SCHEMA_VERSION,
                "knowledge": storage_migration.KNOWLEDGE_SCHEMA_VERSION,
                "yuanlei": 2,
            }
        ),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        upgrade_yuanlei_schema_v1_to_v2=lambda: _record(calls, "upgrade_yuanlei_v1_v2"),
        upgrade_yuanlei_schema_v2_to_v3=lambda: _record(calls, "upgrade_yuanlei_v2_v3"),
        upgrade_yuanlei_schema_v3_to_v4=lambda: _record(calls, "upgrade_yuanlei_v3_v4"),
        upgrade_yuanlei_schema_v4_to_v5=lambda: _record(calls, "upgrade_yuanlei_v4_v5"),
        upgrade_yuanlei_schema_v5_to_v6=lambda: _record(calls, "upgrade_yuanlei_v5_v6"),
        upgrade_yuanlei_schema_v6_to_v7=lambda: _record(calls, "upgrade_yuanlei_v6_v7"),
        upgrade_yuanlei_schema_v7_to_v8=lambda: _record(calls, "upgrade_yuanlei_v7_v8"),
        upgrade_yuanlei_schema_v8_to_v9=lambda: _record(calls, "upgrade_yuanlei_v8_v9"),
        upgrade_yuanlei_schema_v9_to_v10=lambda: _record(calls, "upgrade_yuanlei_v9_v10"),
        upgrade_yuanlei_schema_v10_to_v11=lambda: _record(calls, "upgrade_yuanlei_v10_v11"),
        upgrade_yuanlei_schema_v11_to_v12=lambda: _record(calls, "upgrade_yuanlei_v11_v12"),
        upgrade_yuanlei_schema_v12_to_v13=lambda: _record(calls, "upgrade_yuanlei_v12_v13"),
        upgrade_yuanlei_schema_v13_to_v14=lambda: _record(calls, "upgrade_yuanlei_v13_v14"),
        upgrade_yuanlei_schema_v14_to_v15=lambda: _record(calls, "upgrade_yuanlei_v14_v15"),
        upgrade_yuanlei_schema_v15_to_v16=lambda: _record(calls, "upgrade_yuanlei_v15_v16"),
        upgrade_yuanlei_schema_v16_to_v17=lambda: _record(calls, "upgrade_yuanlei_v16_v17"),
        upgrade_yuanlei_schema_v17_to_v18=lambda: _record(calls, "upgrade_yuanlei_v17_v18"),
        upgrade_yuanlei_schema_v18_to_v19=lambda: _record(calls, "upgrade_yuanlei_v18_v19"),
        upgrade_yuanlei_schema_v19_to_v20=lambda: _record(calls, "upgrade_yuanlei_v19_v20"),
        upgrade_yuanlei_schema_v20_to_v21=lambda: _record(calls, "upgrade_yuanlei_v20_v21"),
        upgrade_yuanlei_schema_v21_to_v22=lambda: _record(calls, "upgrade_yuanlei_v21_v22"),
        upgrade_yuanlei_schema_v22_to_v23=lambda: _record(calls, "upgrade_yuanlei_v22_v23"),
        upgrade_yuanlei_schema_v23_to_v24=lambda: _record(calls, "upgrade_yuanlei_v23_v24"),
        upgrade_yuanlei_schema_v24_to_v25=lambda: _record(calls, "upgrade_yuanlei_v24_v25"),
        upgrade_yuanlei_schema_v25_to_v26=lambda: _record(calls, "upgrade_yuanlei_v25_v26"),
        upgrade_yuanlei_schema_v26_to_v27=lambda: _record(calls, "upgrade_yuanlei_v26_v27"),
        upgrade_yuanlei_schema_v27_to_v28=lambda: _record(calls, "upgrade_yuanlei_v27_v28"),
        upgrade_yuanlei_schema_v28_to_v29=lambda: _record(calls, "upgrade_yuanlei_v28_v29"),
        upgrade_yuanlei_schema_v29_to_v30=lambda: _record(calls, "upgrade_yuanlei_v29_v30"),
        upgrade_yuanlei_schema_v30_to_v31=lambda: _record(calls, "upgrade_yuanlei_v30_v31"),
        upgrade_yuanlei_schema_v31_to_v32=lambda: _record(calls, "upgrade_yuanlei_v31_v32"),
        upgrade_yuanlei_schema_v32_to_v33=lambda: _record(calls, "work_results"),
        upgrade_yuanlei_schema_v33_to_v34=lambda: _record(calls, "work_context"),
        upgrade_yuanlei_schema_v34_to_v35=lambda: _record(calls, "execution_results"),
        upgrade_yuanlei_schema_v35_to_v36=lambda: _record(calls, "topic_followup"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(False, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setattr(
        storage_migration,
        "_converge_database_state",
        lambda *, fail_nonterminal_runs: _record(calls, f"converge:{fail_nonterminal_runs}"),
    )
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", lambda _db: _record(calls, "skills"))
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: calls.append("mark_skills"))
    monkeypatch.setattr(storage_migration, "migrate_runtime_storage_identity", lambda: calls.append("runtime_identity"))

    await storage_migration.main()

    assert "upgrade_yuanlei_v1_v2" not in calls
    assert "upgrade_yuanlei_v2_v3" in calls
    assert "upgrade_yuanlei_v3_v4" in calls
    assert "upgrade_yuanlei_v4_v5" in calls
    assert "upgrade_yuanlei_v5_v6" in calls
    assert "upgrade_yuanlei_v6_v7" in calls
    assert "upgrade_yuanlei_v7_v8" in calls
    assert "upgrade_yuanlei_v8_v9" in calls
    assert "upgrade_yuanlei_v9_v10" in calls
    version_call = f"version:yuanlei:{storage_migration.YUANLEI_SCHEMA_VERSION}"
    assert calls.index("upgrade_yuanlei_v2_v3") < calls.index("upgrade_yuanlei_v3_v4")
    assert calls.index("upgrade_yuanlei_v3_v4") < calls.index("upgrade_yuanlei_v4_v5")
    assert calls.index("upgrade_yuanlei_v4_v5") < calls.index("upgrade_yuanlei_v5_v6")
    assert calls.index("upgrade_yuanlei_v5_v6") < calls.index("upgrade_yuanlei_v6_v7")
    assert calls.index("upgrade_yuanlei_v6_v7") < calls.index("upgrade_yuanlei_v7_v8")
    assert calls.index("upgrade_yuanlei_v7_v8") < calls.index("upgrade_yuanlei_v8_v9")
    assert calls.index("upgrade_yuanlei_v8_v9") < calls.index("upgrade_yuanlei_v9_v10")
    assert calls.index("upgrade_yuanlei_v9_v10") < calls.index("upgrade_yuanlei_v10_v11")
    assert calls.index("upgrade_yuanlei_v10_v11") < calls.index("upgrade_yuanlei_v11_v12")
    assert calls.index("upgrade_yuanlei_v11_v12") < calls.index("upgrade_yuanlei_v12_v13")
    assert calls.index("upgrade_yuanlei_v12_v13") < calls.index("upgrade_yuanlei_v13_v14")
    assert calls.index("upgrade_yuanlei_v13_v14") < calls.index("upgrade_yuanlei_v14_v15")
    assert calls.index("upgrade_yuanlei_v14_v15") < calls.index("upgrade_yuanlei_v15_v16")
    assert calls.index("upgrade_yuanlei_v15_v16") < calls.index("upgrade_yuanlei_v16_v17")
    assert calls.index("upgrade_yuanlei_v16_v17") < calls.index("upgrade_yuanlei_v17_v18")
    assert calls.index("upgrade_yuanlei_v17_v18") < calls.index("upgrade_yuanlei_v18_v19")
    assert calls.index("upgrade_yuanlei_v18_v19") < calls.index("upgrade_yuanlei_v19_v20")
    assert calls.index("upgrade_yuanlei_v19_v20") < calls.index("upgrade_yuanlei_v20_v21")
    assert calls.index("upgrade_yuanlei_v20_v21") < calls.index("upgrade_yuanlei_v21_v22")
    assert calls.index("upgrade_yuanlei_v21_v22") < calls.index("upgrade_yuanlei_v22_v23")
    assert calls.index("upgrade_yuanlei_v22_v23") < calls.index("upgrade_yuanlei_v23_v24")
    assert calls.index("upgrade_yuanlei_v23_v24") < calls.index("upgrade_yuanlei_v24_v25")
    assert calls.index("upgrade_yuanlei_v24_v25") < calls.index("upgrade_yuanlei_v27_v28")
    assert calls.index("upgrade_yuanlei_v27_v28") < calls.index("upgrade_yuanlei_v28_v29") < calls.index("upgrade_yuanlei_v29_v30") < calls.index("upgrade_yuanlei_v30_v31") < calls.index(version_call)


@pytest.mark.asyncio
async def test_yuanlei_v3_is_upgraded_to_agent_sandboxes_without_replaying_earlier_steps(monkeypatch):
    calls: list[str] = []
    sessions = [_Session(), _Session(), _Session()]

    @asynccontextmanager
    async def session_context():
        yield sessions.pop(0)

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value(
            {
                "business": storage_migration.BUSINESS_SCHEMA_VERSION,
                "knowledge": storage_migration.KNOWLEDGE_SCHEMA_VERSION,
                "yuanlei": 3,
            }
        ),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        upgrade_yuanlei_schema_v1_to_v2=lambda: _record(calls, "upgrade_yuanlei_v1_v2"),
        upgrade_yuanlei_schema_v2_to_v3=lambda: _record(calls, "upgrade_yuanlei_v2_v3"),
        upgrade_yuanlei_schema_v3_to_v4=lambda: _record(calls, "upgrade_yuanlei_v3_v4"),
        upgrade_yuanlei_schema_v4_to_v5=lambda: _record(calls, "upgrade_yuanlei_v4_v5"),
        upgrade_yuanlei_schema_v5_to_v6=lambda: _record(calls, "upgrade_yuanlei_v5_v6"),
        upgrade_yuanlei_schema_v6_to_v7=lambda: _record(calls, "upgrade_yuanlei_v6_v7"),
        upgrade_yuanlei_schema_v7_to_v8=lambda: _record(calls, "upgrade_yuanlei_v7_v8"),
        upgrade_yuanlei_schema_v8_to_v9=lambda: _record(calls, "upgrade_yuanlei_v8_v9"),
        upgrade_yuanlei_schema_v9_to_v10=lambda: _record(calls, "upgrade_yuanlei_v9_v10"),
        upgrade_yuanlei_schema_v10_to_v11=lambda: _record(calls, "upgrade_yuanlei_v10_v11"),
        upgrade_yuanlei_schema_v11_to_v12=lambda: _record(calls, "upgrade_yuanlei_v11_v12"),
        upgrade_yuanlei_schema_v12_to_v13=lambda: _record(calls, "upgrade_yuanlei_v12_v13"),
        upgrade_yuanlei_schema_v13_to_v14=lambda: _record(calls, "upgrade_yuanlei_v13_v14"),
        upgrade_yuanlei_schema_v14_to_v15=lambda: _record(calls, "upgrade_yuanlei_v14_v15"),
        upgrade_yuanlei_schema_v15_to_v16=lambda: _record(calls, "upgrade_yuanlei_v15_v16"),
        upgrade_yuanlei_schema_v16_to_v17=lambda: _record(calls, "upgrade_yuanlei_v16_v17"),
        upgrade_yuanlei_schema_v17_to_v18=lambda: _record(calls, "upgrade_yuanlei_v17_v18"),
        upgrade_yuanlei_schema_v18_to_v19=lambda: _record(calls, "upgrade_yuanlei_v18_v19"),
        upgrade_yuanlei_schema_v19_to_v20=lambda: _record(calls, "upgrade_yuanlei_v19_v20"),
        upgrade_yuanlei_schema_v20_to_v21=lambda: _record(calls, "upgrade_yuanlei_v20_v21"),
        upgrade_yuanlei_schema_v21_to_v22=lambda: _record(calls, "upgrade_yuanlei_v21_v22"),
        upgrade_yuanlei_schema_v22_to_v23=lambda: _record(calls, "upgrade_yuanlei_v22_v23"),
        upgrade_yuanlei_schema_v23_to_v24=lambda: _record(calls, "upgrade_yuanlei_v23_v24"),
        upgrade_yuanlei_schema_v24_to_v25=lambda: _record(calls, "upgrade_yuanlei_v24_v25"),
        upgrade_yuanlei_schema_v25_to_v26=lambda: _record(calls, "upgrade_yuanlei_v25_v26"),
        upgrade_yuanlei_schema_v26_to_v27=lambda: _record(calls, "upgrade_yuanlei_v26_v27"),
        upgrade_yuanlei_schema_v27_to_v28=lambda: _record(calls, "upgrade_yuanlei_v27_v28"),
        upgrade_yuanlei_schema_v28_to_v29=lambda: _record(calls, "upgrade_yuanlei_v28_v29"),
        upgrade_yuanlei_schema_v29_to_v30=lambda: _record(calls, "upgrade_yuanlei_v29_v30"),
        upgrade_yuanlei_schema_v30_to_v31=lambda: _record(calls, "upgrade_yuanlei_v30_v31"),
        upgrade_yuanlei_schema_v31_to_v32=lambda: _record(calls, "upgrade_yuanlei_v31_v32"),
        upgrade_yuanlei_schema_v32_to_v33=lambda: _record(calls, "work_results"),
        upgrade_yuanlei_schema_v33_to_v34=lambda: _record(calls, "work_context"),
        upgrade_yuanlei_schema_v34_to_v35=lambda: _record(calls, "execution_results"),
        upgrade_yuanlei_schema_v35_to_v36=lambda: _record(calls, "topic_followup"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(False, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setattr(
        storage_migration,
        "_converge_database_state",
        lambda *, fail_nonterminal_runs: _record(calls, f"converge:{fail_nonterminal_runs}"),
    )
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", lambda _db: _record(calls, "skills"))
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: calls.append("mark_skills"))
    monkeypatch.setattr(storage_migration, "migrate_runtime_storage_identity", lambda: calls.append("runtime_identity"))

    await storage_migration.main()

    assert "upgrade_yuanlei_v1_v2" not in calls
    assert "upgrade_yuanlei_v2_v3" not in calls
    assert "upgrade_yuanlei_v3_v4" in calls
    assert "upgrade_yuanlei_v4_v5" in calls
    assert "upgrade_yuanlei_v5_v6" in calls
    assert "upgrade_yuanlei_v6_v7" in calls
    assert "upgrade_yuanlei_v7_v8" in calls
    assert "upgrade_yuanlei_v8_v9" in calls
    assert "upgrade_yuanlei_v9_v10" in calls
    version_call = f"version:yuanlei:{storage_migration.YUANLEI_SCHEMA_VERSION}"
    assert calls.index("upgrade_yuanlei_v3_v4") < calls.index("upgrade_yuanlei_v4_v5")
    assert calls.index("upgrade_yuanlei_v4_v5") < calls.index("upgrade_yuanlei_v5_v6")
    assert calls.index("upgrade_yuanlei_v5_v6") < calls.index("upgrade_yuanlei_v6_v7")
    assert calls.index("upgrade_yuanlei_v6_v7") < calls.index("upgrade_yuanlei_v7_v8")
    assert calls.index("upgrade_yuanlei_v7_v8") < calls.index("upgrade_yuanlei_v8_v9")
    assert calls.index("upgrade_yuanlei_v8_v9") < calls.index("upgrade_yuanlei_v9_v10")
    assert calls.index("upgrade_yuanlei_v9_v10") < calls.index("upgrade_yuanlei_v10_v11")
    assert calls.index("upgrade_yuanlei_v10_v11") < calls.index("upgrade_yuanlei_v11_v12")
    assert calls.index("upgrade_yuanlei_v11_v12") < calls.index("upgrade_yuanlei_v12_v13")
    assert calls.index("upgrade_yuanlei_v12_v13") < calls.index("upgrade_yuanlei_v13_v14")
    assert calls.index("upgrade_yuanlei_v13_v14") < calls.index("upgrade_yuanlei_v14_v15")
    assert calls.index("upgrade_yuanlei_v14_v15") < calls.index("upgrade_yuanlei_v15_v16")
    assert calls.index("upgrade_yuanlei_v15_v16") < calls.index("upgrade_yuanlei_v16_v17")
    assert calls.index("upgrade_yuanlei_v16_v17") < calls.index("upgrade_yuanlei_v17_v18")
    assert calls.index("upgrade_yuanlei_v17_v18") < calls.index("upgrade_yuanlei_v18_v19")
    assert calls.index("upgrade_yuanlei_v18_v19") < calls.index("upgrade_yuanlei_v19_v20")
    assert calls.index("upgrade_yuanlei_v19_v20") < calls.index("upgrade_yuanlei_v20_v21")
    assert calls.index("upgrade_yuanlei_v20_v21") < calls.index("upgrade_yuanlei_v21_v22")
    assert calls.index("upgrade_yuanlei_v21_v22") < calls.index("upgrade_yuanlei_v22_v23")
    assert calls.index("upgrade_yuanlei_v22_v23") < calls.index("upgrade_yuanlei_v23_v24")
    assert calls.index("upgrade_yuanlei_v23_v24") < calls.index("upgrade_yuanlei_v24_v25")
    assert calls.index("upgrade_yuanlei_v24_v25") < calls.index("upgrade_yuanlei_v27_v28")
    assert calls.index("upgrade_yuanlei_v27_v28") < calls.index("upgrade_yuanlei_v28_v29") < calls.index("upgrade_yuanlei_v29_v30") < calls.index("upgrade_yuanlei_v30_v31") < calls.index(version_call)


@pytest.mark.asyncio
async def test_yuanlei_v4_is_upgraded_to_coding_credentials_without_replaying_earlier_steps(monkeypatch):
    calls: list[str] = []
    sessions = [_Session(), _Session(), _Session()]

    @asynccontextmanager
    async def session_context():
        yield sessions.pop(0)

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value(
            {
                "business": storage_migration.BUSINESS_SCHEMA_VERSION,
                "knowledge": storage_migration.KNOWLEDGE_SCHEMA_VERSION,
                "yuanlei": 4,
            }
        ),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        upgrade_yuanlei_schema_v1_to_v2=lambda: _record(calls, "upgrade_yuanlei_v1_v2"),
        upgrade_yuanlei_schema_v2_to_v3=lambda: _record(calls, "upgrade_yuanlei_v2_v3"),
        upgrade_yuanlei_schema_v3_to_v4=lambda: _record(calls, "upgrade_yuanlei_v3_v4"),
        upgrade_yuanlei_schema_v4_to_v5=lambda: _record(calls, "upgrade_yuanlei_v4_v5"),
        upgrade_yuanlei_schema_v5_to_v6=lambda: _record(calls, "upgrade_yuanlei_v5_v6"),
        upgrade_yuanlei_schema_v6_to_v7=lambda: _record(calls, "upgrade_yuanlei_v6_v7"),
        upgrade_yuanlei_schema_v7_to_v8=lambda: _record(calls, "upgrade_yuanlei_v7_v8"),
        upgrade_yuanlei_schema_v8_to_v9=lambda: _record(calls, "upgrade_yuanlei_v8_v9"),
        upgrade_yuanlei_schema_v9_to_v10=lambda: _record(calls, "upgrade_yuanlei_v9_v10"),
        upgrade_yuanlei_schema_v10_to_v11=lambda: _record(calls, "upgrade_yuanlei_v10_v11"),
        upgrade_yuanlei_schema_v11_to_v12=lambda: _record(calls, "upgrade_yuanlei_v11_v12"),
        upgrade_yuanlei_schema_v12_to_v13=lambda: _record(calls, "upgrade_yuanlei_v12_v13"),
        upgrade_yuanlei_schema_v13_to_v14=lambda: _record(calls, "upgrade_yuanlei_v13_v14"),
        upgrade_yuanlei_schema_v14_to_v15=lambda: _record(calls, "upgrade_yuanlei_v14_v15"),
        upgrade_yuanlei_schema_v15_to_v16=lambda: _record(calls, "upgrade_yuanlei_v15_v16"),
        upgrade_yuanlei_schema_v16_to_v17=lambda: _record(calls, "upgrade_yuanlei_v16_v17"),
        upgrade_yuanlei_schema_v17_to_v18=lambda: _record(calls, "upgrade_yuanlei_v17_v18"),
        upgrade_yuanlei_schema_v18_to_v19=lambda: _record(calls, "upgrade_yuanlei_v18_v19"),
        upgrade_yuanlei_schema_v19_to_v20=lambda: _record(calls, "upgrade_yuanlei_v19_v20"),
        upgrade_yuanlei_schema_v20_to_v21=lambda: _record(calls, "upgrade_yuanlei_v20_v21"),
        upgrade_yuanlei_schema_v21_to_v22=lambda: _record(calls, "upgrade_yuanlei_v21_v22"),
        upgrade_yuanlei_schema_v22_to_v23=lambda: _record(calls, "upgrade_yuanlei_v22_v23"),
        upgrade_yuanlei_schema_v23_to_v24=lambda: _record(calls, "upgrade_yuanlei_v23_v24"),
        upgrade_yuanlei_schema_v24_to_v25=lambda: _record(calls, "upgrade_yuanlei_v24_v25"),
        upgrade_yuanlei_schema_v25_to_v26=lambda: _record(calls, "upgrade_yuanlei_v25_v26"),
        upgrade_yuanlei_schema_v26_to_v27=lambda: _record(calls, "upgrade_yuanlei_v26_v27"),
        upgrade_yuanlei_schema_v27_to_v28=lambda: _record(calls, "upgrade_yuanlei_v27_v28"),
        upgrade_yuanlei_schema_v28_to_v29=lambda: _record(calls, "upgrade_yuanlei_v28_v29"),
        upgrade_yuanlei_schema_v29_to_v30=lambda: _record(calls, "upgrade_yuanlei_v29_v30"),
        upgrade_yuanlei_schema_v30_to_v31=lambda: _record(calls, "upgrade_yuanlei_v30_v31"),
        upgrade_yuanlei_schema_v31_to_v32=lambda: _record(calls, "upgrade_yuanlei_v31_v32"),
        upgrade_yuanlei_schema_v32_to_v33=lambda: _record(calls, "work_results"),
        upgrade_yuanlei_schema_v33_to_v34=lambda: _record(calls, "work_context"),
        upgrade_yuanlei_schema_v34_to_v35=lambda: _record(calls, "execution_results"),
        upgrade_yuanlei_schema_v35_to_v36=lambda: _record(calls, "topic_followup"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(False, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setattr(
        storage_migration,
        "_converge_database_state",
        lambda *, fail_nonterminal_runs: _record(calls, f"converge:{fail_nonterminal_runs}"),
    )
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", lambda _db: _record(calls, "skills"))
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: calls.append("mark_skills"))
    monkeypatch.setattr(storage_migration, "migrate_runtime_storage_identity", lambda: calls.append("runtime_identity"))

    await storage_migration.main()

    assert "upgrade_yuanlei_v1_v2" not in calls
    assert "upgrade_yuanlei_v2_v3" not in calls
    assert "upgrade_yuanlei_v3_v4" not in calls
    assert "upgrade_yuanlei_v4_v5" in calls
    assert "upgrade_yuanlei_v5_v6" in calls
    assert "upgrade_yuanlei_v6_v7" in calls
    assert "upgrade_yuanlei_v7_v8" in calls
    assert "upgrade_yuanlei_v8_v9" in calls
    assert "upgrade_yuanlei_v9_v10" in calls
    version_call = f"version:yuanlei:{storage_migration.YUANLEI_SCHEMA_VERSION}"
    assert calls.index("upgrade_yuanlei_v4_v5") < calls.index("upgrade_yuanlei_v5_v6")
    assert calls.index("upgrade_yuanlei_v5_v6") < calls.index("upgrade_yuanlei_v6_v7")
    assert calls.index("upgrade_yuanlei_v6_v7") < calls.index("upgrade_yuanlei_v7_v8")
    assert calls.index("upgrade_yuanlei_v7_v8") < calls.index("upgrade_yuanlei_v8_v9")
    assert calls.index("upgrade_yuanlei_v8_v9") < calls.index("upgrade_yuanlei_v9_v10")
    assert calls.index("upgrade_yuanlei_v9_v10") < calls.index("upgrade_yuanlei_v10_v11")
    assert calls.index("upgrade_yuanlei_v10_v11") < calls.index("upgrade_yuanlei_v11_v12")
    assert calls.index("upgrade_yuanlei_v11_v12") < calls.index("upgrade_yuanlei_v12_v13")
    assert calls.index("upgrade_yuanlei_v12_v13") < calls.index("upgrade_yuanlei_v13_v14")
    assert calls.index("upgrade_yuanlei_v13_v14") < calls.index("upgrade_yuanlei_v14_v15")
    assert calls.index("upgrade_yuanlei_v14_v15") < calls.index("upgrade_yuanlei_v15_v16")
    assert calls.index("upgrade_yuanlei_v15_v16") < calls.index("upgrade_yuanlei_v16_v17")
    assert calls.index("upgrade_yuanlei_v16_v17") < calls.index("upgrade_yuanlei_v17_v18")
    assert calls.index("upgrade_yuanlei_v17_v18") < calls.index("upgrade_yuanlei_v18_v19")
    assert calls.index("upgrade_yuanlei_v18_v19") < calls.index("upgrade_yuanlei_v19_v20")
    assert calls.index("upgrade_yuanlei_v19_v20") < calls.index("upgrade_yuanlei_v20_v21")
    assert calls.index("upgrade_yuanlei_v20_v21") < calls.index("upgrade_yuanlei_v21_v22")
    assert calls.index("upgrade_yuanlei_v21_v22") < calls.index("upgrade_yuanlei_v22_v23")
    assert calls.index("upgrade_yuanlei_v22_v23") < calls.index("upgrade_yuanlei_v23_v24")
    assert calls.index("upgrade_yuanlei_v23_v24") < calls.index("upgrade_yuanlei_v24_v25")
    assert calls.index("upgrade_yuanlei_v24_v25") < calls.index("upgrade_yuanlei_v27_v28")
    assert calls.index("upgrade_yuanlei_v27_v28") < calls.index("upgrade_yuanlei_v28_v29") < calls.index("upgrade_yuanlei_v29_v30") < calls.index("upgrade_yuanlei_v30_v31") < calls.index(version_call)


@pytest.mark.asyncio
async def test_yuanlei_v5_is_upgraded_to_coding_sessions_without_replaying_earlier_steps(monkeypatch):
    calls: list[str] = []
    sessions = [_Session(), _Session(), _Session()]

    @asynccontextmanager
    async def session_context():
        yield sessions.pop(0)

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value(
            {
                "business": storage_migration.BUSINESS_SCHEMA_VERSION,
                "knowledge": storage_migration.KNOWLEDGE_SCHEMA_VERSION,
                "yuanlei": 5,
            }
        ),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        upgrade_yuanlei_schema_v1_to_v2=lambda: _record(calls, "upgrade_yuanlei_v1_v2"),
        upgrade_yuanlei_schema_v2_to_v3=lambda: _record(calls, "upgrade_yuanlei_v2_v3"),
        upgrade_yuanlei_schema_v3_to_v4=lambda: _record(calls, "upgrade_yuanlei_v3_v4"),
        upgrade_yuanlei_schema_v4_to_v5=lambda: _record(calls, "upgrade_yuanlei_v4_v5"),
        upgrade_yuanlei_schema_v5_to_v6=lambda: _record(calls, "upgrade_yuanlei_v5_v6"),
        upgrade_yuanlei_schema_v6_to_v7=lambda: _record(calls, "upgrade_yuanlei_v6_v7"),
        upgrade_yuanlei_schema_v7_to_v8=lambda: _record(calls, "upgrade_yuanlei_v7_v8"),
        upgrade_yuanlei_schema_v8_to_v9=lambda: _record(calls, "upgrade_yuanlei_v8_v9"),
        upgrade_yuanlei_schema_v9_to_v10=lambda: _record(calls, "upgrade_yuanlei_v9_v10"),
        upgrade_yuanlei_schema_v10_to_v11=lambda: _record(calls, "upgrade_yuanlei_v10_v11"),
        upgrade_yuanlei_schema_v11_to_v12=lambda: _record(calls, "upgrade_yuanlei_v11_v12"),
        upgrade_yuanlei_schema_v12_to_v13=lambda: _record(calls, "upgrade_yuanlei_v12_v13"),
        upgrade_yuanlei_schema_v13_to_v14=lambda: _record(calls, "upgrade_yuanlei_v13_v14"),
        upgrade_yuanlei_schema_v14_to_v15=lambda: _record(calls, "upgrade_yuanlei_v14_v15"),
        upgrade_yuanlei_schema_v15_to_v16=lambda: _record(calls, "upgrade_yuanlei_v15_v16"),
        upgrade_yuanlei_schema_v16_to_v17=lambda: _record(calls, "upgrade_yuanlei_v16_v17"),
        upgrade_yuanlei_schema_v17_to_v18=lambda: _record(calls, "upgrade_yuanlei_v17_v18"),
        upgrade_yuanlei_schema_v18_to_v19=lambda: _record(calls, "upgrade_yuanlei_v18_v19"),
        upgrade_yuanlei_schema_v19_to_v20=lambda: _record(calls, "upgrade_yuanlei_v19_v20"),
        upgrade_yuanlei_schema_v20_to_v21=lambda: _record(calls, "upgrade_yuanlei_v20_v21"),
        upgrade_yuanlei_schema_v21_to_v22=lambda: _record(calls, "upgrade_yuanlei_v21_v22"),
        upgrade_yuanlei_schema_v22_to_v23=lambda: _record(calls, "upgrade_yuanlei_v22_v23"),
        upgrade_yuanlei_schema_v23_to_v24=lambda: _record(calls, "upgrade_yuanlei_v23_v24"),
        upgrade_yuanlei_schema_v24_to_v25=lambda: _record(calls, "upgrade_yuanlei_v24_v25"),
        upgrade_yuanlei_schema_v25_to_v26=lambda: _record(calls, "upgrade_yuanlei_v25_v26"),
        upgrade_yuanlei_schema_v26_to_v27=lambda: _record(calls, "upgrade_yuanlei_v26_v27"),
        upgrade_yuanlei_schema_v27_to_v28=lambda: _record(calls, "upgrade_yuanlei_v27_v28"),
        upgrade_yuanlei_schema_v28_to_v29=lambda: _record(calls, "upgrade_yuanlei_v28_v29"),
        upgrade_yuanlei_schema_v29_to_v30=lambda: _record(calls, "upgrade_yuanlei_v29_v30"),
        upgrade_yuanlei_schema_v30_to_v31=lambda: _record(calls, "upgrade_yuanlei_v30_v31"),
        upgrade_yuanlei_schema_v31_to_v32=lambda: _record(calls, "upgrade_yuanlei_v31_v32"),
        upgrade_yuanlei_schema_v32_to_v33=lambda: _record(calls, "work_results"),
        upgrade_yuanlei_schema_v33_to_v34=lambda: _record(calls, "work_context"),
        upgrade_yuanlei_schema_v34_to_v35=lambda: _record(calls, "execution_results"),
        upgrade_yuanlei_schema_v35_to_v36=lambda: _record(calls, "topic_followup"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(False, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setattr(
        storage_migration,
        "_converge_database_state",
        lambda *, fail_nonterminal_runs: _record(calls, f"converge:{fail_nonterminal_runs}"),
    )
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", lambda _db: _record(calls, "skills"))
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: calls.append("mark_skills"))
    monkeypatch.setattr(storage_migration, "migrate_runtime_storage_identity", lambda: calls.append("runtime_identity"))

    await storage_migration.main()

    assert "upgrade_yuanlei_v1_v2" not in calls
    assert "upgrade_yuanlei_v2_v3" not in calls
    assert "upgrade_yuanlei_v3_v4" not in calls
    assert "upgrade_yuanlei_v4_v5" not in calls
    assert "upgrade_yuanlei_v5_v6" in calls
    assert "upgrade_yuanlei_v6_v7" in calls
    assert "upgrade_yuanlei_v7_v8" in calls
    assert "upgrade_yuanlei_v8_v9" in calls
    assert "upgrade_yuanlei_v9_v10" in calls
    version_call = f"version:yuanlei:{storage_migration.YUANLEI_SCHEMA_VERSION}"
    assert calls.index("upgrade_yuanlei_v5_v6") < calls.index("upgrade_yuanlei_v6_v7")
    assert calls.index("upgrade_yuanlei_v6_v7") < calls.index("upgrade_yuanlei_v7_v8")
    assert calls.index("upgrade_yuanlei_v7_v8") < calls.index("upgrade_yuanlei_v8_v9")
    assert calls.index("upgrade_yuanlei_v8_v9") < calls.index("upgrade_yuanlei_v9_v10")
    assert calls.index("upgrade_yuanlei_v9_v10") < calls.index("upgrade_yuanlei_v10_v11")
    assert calls.index("upgrade_yuanlei_v10_v11") < calls.index("upgrade_yuanlei_v11_v12")
    assert calls.index("upgrade_yuanlei_v11_v12") < calls.index("upgrade_yuanlei_v12_v13")
    assert calls.index("upgrade_yuanlei_v12_v13") < calls.index("upgrade_yuanlei_v13_v14")
    assert calls.index("upgrade_yuanlei_v13_v14") < calls.index("upgrade_yuanlei_v14_v15")
    assert calls.index("upgrade_yuanlei_v14_v15") < calls.index("upgrade_yuanlei_v15_v16")
    assert calls.index("upgrade_yuanlei_v15_v16") < calls.index("upgrade_yuanlei_v16_v17")
    assert calls.index("upgrade_yuanlei_v16_v17") < calls.index("upgrade_yuanlei_v17_v18")
    assert calls.index("upgrade_yuanlei_v17_v18") < calls.index("upgrade_yuanlei_v18_v19")
    assert calls.index("upgrade_yuanlei_v18_v19") < calls.index("upgrade_yuanlei_v19_v20")
    assert calls.index("upgrade_yuanlei_v19_v20") < calls.index("upgrade_yuanlei_v20_v21")
    assert calls.index("upgrade_yuanlei_v20_v21") < calls.index("upgrade_yuanlei_v21_v22")
    assert calls.index("upgrade_yuanlei_v21_v22") < calls.index("upgrade_yuanlei_v22_v23")
    assert calls.index("upgrade_yuanlei_v22_v23") < calls.index("upgrade_yuanlei_v23_v24")
    assert calls.index("upgrade_yuanlei_v23_v24") < calls.index("upgrade_yuanlei_v24_v25")
    assert calls.index("upgrade_yuanlei_v24_v25") < calls.index("upgrade_yuanlei_v27_v28")
    assert calls.index("upgrade_yuanlei_v27_v28") < calls.index("upgrade_yuanlei_v28_v29") < calls.index("upgrade_yuanlei_v29_v30") < calls.index("upgrade_yuanlei_v30_v31") < calls.index(version_call)


@pytest.mark.asyncio
async def test_yuanlei_v20_is_upgraded_to_inbox_occurrences(monkeypatch):
    """存量 v20 库只执行收件箱发生过程迁移并记录新版本，不回放更早步骤。"""
    calls: list[str] = []
    sessions = [_Session(), _Session(), _Session()]

    @asynccontextmanager
    async def session_context():
        yield sessions.pop(0)

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value(
            {
                "business": storage_migration.BUSINESS_SCHEMA_VERSION,
                "knowledge": storage_migration.KNOWLEDGE_SCHEMA_VERSION,
                "yuanlei": 20,
            }
        ),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        upgrade_yuanlei_schema_v20_to_v21=lambda: _record(calls, "upgrade_yuanlei_v20_v21"),
        upgrade_yuanlei_schema_v21_to_v22=lambda: _record(calls, "upgrade_yuanlei_v21_v22"),
        upgrade_yuanlei_schema_v22_to_v23=lambda: _record(calls, "upgrade_yuanlei_v22_v23"),
        upgrade_yuanlei_schema_v23_to_v24=lambda: _record(calls, "upgrade_yuanlei_v23_v24"),
        upgrade_yuanlei_schema_v24_to_v25=lambda: _record(calls, "upgrade_yuanlei_v24_v25"),
        upgrade_yuanlei_schema_v25_to_v26=lambda: _record(calls, "upgrade_yuanlei_v25_v26"),
        upgrade_yuanlei_schema_v26_to_v27=lambda: _record(calls, "upgrade_yuanlei_v26_v27"),
        upgrade_yuanlei_schema_v27_to_v28=lambda: _record(calls, "upgrade_yuanlei_v27_v28"),
        upgrade_yuanlei_schema_v28_to_v29=lambda: _record(calls, "upgrade_yuanlei_v28_v29"),
        upgrade_yuanlei_schema_v29_to_v30=lambda: _record(calls, "upgrade_yuanlei_v29_v30"),
        upgrade_yuanlei_schema_v30_to_v31=lambda: _record(calls, "upgrade_yuanlei_v30_v31"),
        upgrade_yuanlei_schema_v31_to_v32=lambda: _record(calls, "upgrade_yuanlei_v31_v32"),
        upgrade_yuanlei_schema_v32_to_v33=lambda: _record(calls, "work_results"),
        upgrade_yuanlei_schema_v33_to_v34=lambda: _record(calls, "work_context"),
        upgrade_yuanlei_schema_v34_to_v35=lambda: _record(calls, "execution_results"),
        upgrade_yuanlei_schema_v35_to_v36=lambda: _record(calls, "topic_followup"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(False, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setattr(
        storage_migration,
        "_converge_database_state",
        lambda *, fail_nonterminal_runs: _record(calls, f"converge:{fail_nonterminal_runs}"),
    )
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", lambda _db: _record(calls, "skills"))
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: calls.append("mark_skills"))
    monkeypatch.setattr(storage_migration, "migrate_runtime_storage_identity", lambda: calls.append("runtime_identity"))

    await storage_migration.main()

    version_call = f"version:yuanlei:{storage_migration.YUANLEI_SCHEMA_VERSION}"
    assert "upgrade_yuanlei_v19_v20" not in calls
    assert "upgrade_yuanlei_v20_v21" in calls
    assert calls.index("upgrade_yuanlei_v20_v21") < calls.index("upgrade_yuanlei_v21_v22")
    assert calls.index("upgrade_yuanlei_v21_v22") < calls.index("upgrade_yuanlei_v22_v23")
    assert calls.index("upgrade_yuanlei_v22_v23") < calls.index("upgrade_yuanlei_v23_v24")
    assert calls.index("upgrade_yuanlei_v23_v24") < calls.index("upgrade_yuanlei_v24_v25")
    assert calls.index("upgrade_yuanlei_v24_v25") < calls.index("upgrade_yuanlei_v27_v28")
    assert calls.index("upgrade_yuanlei_v27_v28") < calls.index("upgrade_yuanlei_v28_v29") < calls.index("upgrade_yuanlei_v29_v30") < calls.index("upgrade_yuanlei_v30_v31") < calls.index(version_call)


@pytest.mark.asyncio
@pytest.mark.parametrize("unsupported_version", [1, 3, 4, 5, 6, storage_migration.BUSINESS_SCHEMA_VERSION + 1])
async def test_main_rejects_unsupported_business_schema_before_ddl(monkeypatch, unsupported_version: int):
    calls: list[str] = []

    @asynccontextmanager
    async def session_context():
        yield _Session()

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value(
            {"business": unsupported_version, "knowledge": storage_migration.KNOWLEDGE_SCHEMA_VERSION}
        ),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(False, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)

    with pytest.raises(RuntimeError, match=f"Unsupported business schema version: {unsupported_version}"):
        await storage_migration.main()

    assert calls == ["initialize", "schema_lock", "create_schema_version_table", "close"]


@pytest.mark.asyncio
@pytest.mark.parametrize("previous_version", [2])
async def test_supported_business_schema_is_converged_and_versioned_as_current(monkeypatch, previous_version):
    calls: list[str] = []
    sessions = [_Session(), _Session(), _Session()]

    @asynccontextmanager
    async def session_context():
        yield sessions.pop(0)

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value(
            {"business": previous_version, "knowledge": storage_migration.KNOWLEDGE_SCHEMA_VERSION}
        ),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        create_business_tables=lambda: _record(calls, "create_business"),
        create_knowledge_tables=lambda: _record(calls, "create_knowledge"),
        ensure_business_schema=lambda: _record(calls, "business_schema"),
        ensure_knowledge_schema=lambda: _record(calls, "knowledge_schema"),
        setup_langgraph_checkpointer=lambda: _record(calls, "checkpoint"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(False, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setattr(
        storage_migration,
        "_converge_database_state",
        lambda *, fail_nonterminal_runs: _record(calls, f"converge:{fail_nonterminal_runs}"),
    )
    monkeypatch.setattr(storage_migration, "_ensure_yuanlei_schema", lambda: _record(calls, "yuanlei_schema"))
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", lambda _db: _record(calls, "skills"))
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: calls.append("mark_skills"))
    monkeypatch.setattr(storage_migration, "migrate_runtime_storage_identity", lambda: calls.append("runtime_identity"))

    await storage_migration.main()

    assert "business_schema" in calls
    assert f"version:business:{storage_migration.BUSINESS_SCHEMA_VERSION}" in calls
    assert {"create_business", "checkpoint", "knowledge_schema"}.isdisjoint(calls)


@pytest.mark.asyncio
async def test_failed_business_migration_does_not_record_version(monkeypatch):
    calls: list[str] = []

    @asynccontextmanager
    async def session_context():
        yield _Session()

    async def fail_checkpoint_setup():
        calls.append("checkpoint")
        raise RuntimeError("broken checkpoint migration")

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value({}),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        create_business_tables=lambda: _record(calls, "create_business"),
        create_knowledge_tables=lambda: _record(calls, "create_knowledge"),
        ensure_business_schema=lambda: _record(calls, "business_schema"),
        ensure_knowledge_schema=lambda: _record(calls, "knowledge_schema"),
        setup_langgraph_checkpointer=fail_checkpoint_setup,
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(False, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)

    with pytest.raises(RuntimeError, match="broken checkpoint migration"):
        await storage_migration.main()

    assert "business_schema" in calls
    assert f"version:business:{storage_migration.BUSINESS_SCHEMA_VERSION}" not in calls
    assert "create_knowledge" not in calls
    assert calls[-1] == "close"


@pytest.mark.asyncio
async def test_current_schema_does_not_rewrite_workdir_data(monkeypatch):
    calls: list[str] = []
    sessions = [_Session(), _Session(), _Session()]

    @asynccontextmanager
    async def session_context():
        yield sessions.pop(0)

    manager = SimpleNamespace(
        initialize=lambda: calls.append("initialize"),
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "create_schema_version_table"),
        get_schema_versions=lambda: _async_value({}),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "ensure_runtime_scope_width"),
        create_business_tables=lambda: _record(calls, "create"),
        create_knowledge_tables=lambda: _record(calls, "create_knowledge"),
        ensure_business_schema=lambda: _record(calls, "schema"),
        ensure_knowledge_schema=lambda: _record(calls, "knowledge_schema"),
        setup_langgraph_checkpointer=lambda: _record(calls, "checkpoint"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(
        storage_migration,
        "read_v071_workdir_plan",
        lambda _db: _async_value(V071WorkdirMigrationPlan(False, (), ())),
    )
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setattr(
        storage_migration,
        "_converge_database_state",
        lambda *, fail_nonterminal_runs: _record(calls, f"converge:{fail_nonterminal_runs}"),
    )
    monkeypatch.setattr(storage_migration, "_ensure_yuanlei_schema", lambda: _record(calls, "yuanlei_schema"))
    monkeypatch.setattr(storage_migration, "import_v071_workdirs", lambda *_args: calls.append("import"))
    monkeypatch.setattr(storage_migration, "rewrite_v071_workdir_paths", lambda _db: _record(calls, "rewrite"))
    monkeypatch.setattr(storage_migration, "verify_workdir_bindings", lambda _db: _record(calls, "verify"))
    monkeypatch.setattr(storage_migration, "cleanup_v071_thread_sources", lambda *_args: calls.append("cleanup"))
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", lambda _db: _record(calls, "skills"))
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: calls.append("mark_skills"))
    monkeypatch.setattr(
        storage_migration,
        "migrate_runtime_storage_identity",
        lambda: calls.append("runtime_identity"),
    )

    await storage_migration.main()

    assert "converge:False" in calls
    assert "schema" in calls
    assert "skills" in calls
    assert "runtime_identity" in calls
    assert {"import", "rewrite", "verify", "cleanup"}.isdisjoint(calls)


def test_personal_workspace_skills_never_trigger_shared_skill_migration(monkeypatch, tmp_path):
    personal_skill = tmp_path / "user-data/shared/user-1/workspace/agents/skills/notes"
    personal_skill.mkdir(parents=True)
    monkeypatch.setattr(storage_migration, "get_legacy_storage_dir", lambda: tmp_path / "legacy")
    monkeypatch.setattr(storage_migration, "v071_skill_migration_completed", lambda: False)

    assert storage_migration._legacy_skill_roots_exist() is False


@asynccontextmanager
async def _async_context(calls: list[object], value: str):
    calls.append(value)
    yield


async def _record(calls: list[object], value: str) -> None:
    calls.append(value)


async def _async_value(value):
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("old_version", [31, 32, 33, 34, 35])
@pytest.mark.parametrize("fail_followup", [False, True])
async def test_yuanlei_v31_only_adds_project_attributes_before_version_record(
    monkeypatch, old_version, fail_followup
):
    """旧版按链补齐，仅全部成功后记录当前版本。"""
    calls = []

    @asynccontextmanager
    async def session_context():
        yield _Session()

    manager = SimpleNamespace(
        initialize=lambda: None,
        schema_migration_lock=lambda: _async_context(calls, "schema_lock"),
        create_schema_version_table=lambda: _record(calls, "versions"),
        get_schema_versions=lambda: _async_value({
            "business": storage_migration.BUSINESS_SCHEMA_VERSION,
            "knowledge": storage_migration.KNOWLEDGE_SCHEMA_VERSION, "yuanlei": old_version}),
        record_schema_version=lambda domain, version: _record(calls, f"version:{domain}:{version}"),
        ensure_runtime_scope_width=lambda: _record(calls, "runtime_width"),
        upgrade_yuanlei_schema_v31_to_v32=lambda: _record(calls, "project_attributes"),
        upgrade_yuanlei_schema_v32_to_v33=lambda: _record(calls, "work_results"),
        upgrade_yuanlei_schema_v33_to_v34=lambda: _record(calls, "work_context"),
        upgrade_yuanlei_schema_v34_to_v35=lambda: _record(calls, "execution_results"),
        upgrade_yuanlei_schema_v35_to_v36=lambda: _record(calls, "topic_followup"),
        get_async_session_context=session_context,
        close=lambda: _record(calls, "close"),
    )
    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(storage_migration, "read_v071_workdir_plan", lambda db: _async_value(V071WorkdirMigrationPlan(False, (), ())))
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setattr(storage_migration, "_converge_database_state", lambda **kwargs: _record(calls, "converge"))
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", lambda db: _record(calls, "skills"))
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: None)
    monkeypatch.setattr(storage_migration, "migrate_runtime_storage_identity", lambda: None)
    if fail_followup:
        async def fail():
            """模拟新结构迁移失败，验证版本不提前推进。"""
            raise RuntimeError("议题迁移失败")
        manager.upgrade_yuanlei_schema_v35_to_v36 = fail
        with pytest.raises(RuntimeError, match="议题迁移失败"):
            await storage_migration.main()
        assert not any(str(call).startswith("version:yuanlei:") for call in calls)
        return
    await storage_migration.main()
    version = f"version:yuanlei:{storage_migration.YUANLEI_SCHEMA_VERSION}"
    assert calls.index("topic_followup") < calls.index(version)
    if old_version < 35:
        assert calls.index("execution_results") < calls.index("topic_followup")
    else:
        assert "execution_results" not in calls
    if old_version < 34:
        assert calls.index("work_context") < calls.index("execution_results")
    if old_version < 33:
        assert calls.index("work_results") < calls.index("work_context")
    assert calls.count("work_results") == (1 if old_version < 33 else 0)
    assert calls.count("project_attributes") == (1 if old_version == 31 else 0)
