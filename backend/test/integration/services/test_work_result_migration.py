"""真实 PostgreSQL 验收模型迁移保持历史数据并可重入。"""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from yuxi.storage.postgres.manager import PostgresManager

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """隔离 Schema 无需真实 API。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """隔离 Schema 不创建知识资源。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """隔离 Schema 不创建沙盒。"""
    yield


async def test_v32_to_v33_preserves_done_and_reenters():
    """移除新结构重建真实 v32 条件，迁移不会重开或伪造结果。"""
    schema = "p05_migration_" + uuid.uuid4().hex[:12]
    admin = create_async_engine(os.environ["POSTGRES_URL"])
    engine = create_async_engine(os.environ["POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    try:
        async with admin.begin() as db:
            await db.execute(text(f'CREATE SCHEMA "{schema}"'))
        manager = object.__new__(PostgresManager)
        PostgresManager.__init__(manager)
        manager.async_engine = engine
        manager._initialized = True
        await manager.create_business_tables()
        async with engine.begin() as db:
            # 当前模型包含 v35/v36 结果引用，先撤去后续结构再模拟 v32。
            for table in (
                "governance_topic_dispositions",
                "governance_topic_confirmations",
                "project_work_result_topic_feedback",
            ):
                await db.execute(text(f"DROP TABLE {table}"))
            await db.execute(text("DROP TABLE project_work_results"))
            await db.execute(
                text("ALTER TABLE project_work_tasks DROP COLUMN acceptance_criteria, DROP COLUMN criteria_revision")
            )
            await db.execute(
                text("ALTER TABLE project_work_executions DROP CONSTRAINT uq_work_execution_result_source")
            )
            await db.execute(text("ALTER TABLE channel_delegations DROP CONSTRAINT uq_delegation_result_source"))
            await db.execute(
                text(
                    "INSERT INTO "
                    "users(username,uid,password_hash,role,login_failed_count,is_deleted) VALUES "
                    "('qa','qa','x','user',0,0)"
                )
            )
            await db.execute(
                text(
                    "INSERT INTO "
                    """
                    projects(id,uid,name,selection_status,workdir_path,directory_mode,
                    status,created_at,updated_at) VALUES ('p','qa','P','selectable','projects/p',
                    'managed','active',NOW(),NOW())
                    """
                )
            )
            await db.execute(
                text(
                    "INSERT INTO "
                    """
                    project_work_tasks(id,project_id,number,title,description,status,created_by,
                    created_at,updated_at) VALUES ('t','p','QA-GEN-1','历史','旧描述','done',
                    'qa',NOW(),NOW())
                    """
                )
            )
        await manager.upgrade_yuanlei_schema_v32_to_v33()
        await manager.upgrade_yuanlei_schema_v32_to_v33()
        async with engine.connect() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT status,description,acceptance_criteria,criteria_revision FROM "
                        "project_work_tasks WHERE id='t'"
                    )
                )
            ).one()
            assert tuple(row) == ("done", "旧描述", "", 1)
            assert await db.scalar(text("SELECT count(*) FROM project_work_results")) == 0
            assert (
                await db.scalar(
                    text(
                        "SELECT count(*) FROM pg_constraint WHERE conname IN "
                        "('uq_work_execution_result_source','uq_delegation_result_source') AND "
                        "connamespace=CAST(:schema AS regnamespace)"
                    ),
                    {"schema": schema},
                )
                == 2
            )
    finally:
        await engine.dispose()
        async with admin.begin() as db:
            await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
