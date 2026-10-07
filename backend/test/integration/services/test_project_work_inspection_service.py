"""第一负责人周期巡检的真实 PostgreSQL 事务与恢复测试。"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.services import project_work_inspection_service as inspection
from yuxi.storage.postgres.manager import PostgresManager

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _isolated_manager(schema: str):
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    scoped_engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    manager = PostgresManager()
    manager.async_engine = scoped_engine
    manager.AsyncSession = async_sessionmaker(scoped_engine, expire_on_commit=False)
    manager._initialized = True
    await manager.create_business_tables()
    return admin_engine, scoped_engine, manager


async def _drop(schema: str, admin_engine, scoped_engine) -> None:
    await scoped_engine.dispose()
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await admin_engine.dispose()


async def test_inspection_tick_idempotent_recovers_and_does_not_duplicate(monkeypatch):
    """巡检重复 tick 幂等、崩溃可恢复、只在异常变化时产出，且不创建 AgentRun。"""
    schema = f"pytest_inspection_{uuid.uuid4().hex[:16]}"
    admin_engine, scoped_engine, manager = await _isolated_manager(schema)
    monkeypatch.setattr(inspection, "pg_manager", manager)
    try:
        async with scoped_engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO users (username, uid, password_hash, role, login_failed_count, is_deleted) "
                "VALUES ('insp-user', 'insp-user', 'x', 'user', 0, 0)"
            ))
            await connection.execute(text(
                "INSERT INTO projects (id, uid, name, selection_status, workdir_path, directory_mode) "
                "VALUES ('insp-project', 'insp-user', 'Inspect', 'selectable', 'projects/insp', 'managed')"
            ))
            await connection.execute(text(
                "INSERT INTO agents "
                "(slug, backend_id, name, pics, config_json, share_config, is_default, is_subagent) "
                "VALUES ('insp-agent', 'ChatbotAgent', 'Inspector', '[]'::jsonb, "
                "'{}'::jsonb, '{}'::jsonb, FALSE, FALSE)"
            ))
            await connection.execute(text(
                "INSERT INTO project_agents (id, project_id, agent_slug, config_overrides) "
                "VALUES ('insp-binding', 'insp-project', 'insp-agent', '{}'::jsonb)"
            ))
            await connection.execute(text(
                "INSERT INTO project_work_tasks "
                "(id, project_id, number, title, status, primary_owner_agent_slug, inspection_enabled, "
                " inspection_interval_minutes, inspection_next_run_at, created_by, created_at, updated_at) "
                "VALUES ('insp-task', 'insp-project', 'INSP-GEN-000001', 'Inspect me', 'in_progress', 'insp-agent', "
                " TRUE, 60, (now() AT TIME ZONE 'UTC') - INTERVAL '1 minute', 'insp-user', "
                " (now() AT TIME ZONE 'UTC'), (now() AT TIME ZONE 'UTC'))"
            ))

        processed = await inspection.run_project_work_inspection_tick()
        assert processed == 1
        async with scoped_engine.connect() as connection:
            run = (await connection.execute(text(
                "SELECT id, status, finding, summary FROM project_work_inspection_runs"
            ))).one()
            assert run.status == "completed"
            assert run.finding == inspection.FINDING_IN_PROGRESS_WITHOUT_RUN
        # 重复 tick：next_run_at 已推进，不再产生新的巡检事实或产出。
        assert await inspection.run_project_work_inspection_tick() == 0
        async with scoped_engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM project_work_inspection_runs")) == 1
            assert await connection.scalar(text("SELECT count(*) FROM project_work_comments")) == 1
            assert await connection.scalar(text(
                "SELECT count(*) FROM user_inbox_items WHERE kind = 'task_inspection'"
            )) == 1
            assert await connection.scalar(text(
                "SELECT count(*) FROM user_inbox_items WHERE source_id = :run_id"
            ), {"run_id": run.id}) == 1
            assert await connection.scalar(text("SELECT count(*) FROM project_work_executions")) == 0
            assert await connection.scalar(text("SELECT count(*) FROM agent_runs")) == 0
            agent_name = await connection.scalar(text("SELECT author_name FROM project_work_comments LIMIT 1"))
            assert "系统规则巡检" in agent_name

        # worker 崩溃：遗留 claimed 运行由恢复流程收敛；结论未变化时不重复产出。
        async with scoped_engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO project_work_inspection_runs "
                "(id, task_id, project_id, occurrence_key, status, created_at, updated_at) "
                "VALUES ('insp-crash', 'insp-task', 'insp-project', 'scheduled:2020-01-01T00:00:00', "
                " 'claimed', (now() AT TIME ZONE 'UTC') - INTERVAL '5 minutes', "
                " (now() AT TIME ZONE 'UTC') - INTERVAL '5 minutes')"
            ))
        assert await inspection.recover_stale_inspections() == 1
        async with scoped_engine.connect() as connection:
            assert await connection.scalar(text(
                "SELECT status FROM project_work_inspection_runs WHERE id = 'insp-crash'"
            )) == "completed"
            assert await connection.scalar(text("SELECT count(*) FROM project_work_comments")) == 1
            assert await connection.scalar(text(
                "SELECT count(*) FROM user_inbox_items WHERE kind = 'task_inspection'"
            )) == 1

        # 异常变化时产生新的可观察结果。
        async with scoped_engine.begin() as connection:
            await connection.execute(text(
                "UPDATE project_work_tasks SET status = 'blocked' WHERE id = 'insp-task'"
            ))
            await connection.execute(text(
                "INSERT INTO project_work_inspection_runs "
                "(id, task_id, project_id, occurrence_key, status, created_at, updated_at) "
                "VALUES ('insp-changed', 'insp-task', 'insp-project', 'scheduled:2020-01-02T00:00:00', "
                " 'claimed', (now() AT TIME ZONE 'UTC') - INTERVAL '5 minutes', "
                " (now() AT TIME ZONE 'UTC') - INTERVAL '5 minutes')"
            ))
        assert await inspection.recover_stale_inspections() == 1
        async with scoped_engine.connect() as connection:
            assert await connection.scalar(text(
                "SELECT finding FROM project_work_inspection_runs WHERE id = 'insp-changed'"
            )) == inspection.FINDING_BLOCKED
            assert await connection.scalar(text("SELECT count(*) FROM project_work_comments")) == 2
            assert await connection.scalar(text(
                "SELECT count(*) FROM user_inbox_items WHERE kind = 'task_inspection'"
            )) == 2
    finally:
        await _drop(schema, admin_engine, scoped_engine)
