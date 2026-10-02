"""用户收件箱通知幂等写入的真实 PostgreSQL 测试。"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.repositories.user_inbox_repository import UserInboxRepository
from yuxi.storage.postgres.manager import PostgresManager

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """隔离 Schema 不依赖运行中 API。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """隔离 Schema 不创建知识库资源。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """隔离 Schema 不创建沙盒。"""
    yield


async def test_add_once_conflict_returns_existing_notification():
    """同一 (uid, kind, source_id) 重复写入命中唯一键时返回既有行，不同维度各自成行。"""
    schema = f"pytest_inbox_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    scoped_engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        manager = PostgresManager()
        manager.async_engine = scoped_engine
        manager._initialized = True
        await manager.create_business_tables()
        sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)

        async with sessions() as db:
            first = await UserInboxRepository(db).add_once(
                uid="inbox-user", kind="task_failed", source_id="inbox-task", title="首次失败"
            )
            await db.commit()
            first_id = first.id
        async with sessions() as db:
            duplicate = await UserInboxRepository(db).add_once(
                uid="inbox-user", kind="task_failed", source_id="inbox-task", title="重复失败"
            )
            other_kind = await UserInboxRepository(db).add_once(
                uid="inbox-user", kind="task_interrupted", source_id="inbox-task", title="中断"
            )
            other_source = await UserInboxRepository(db).add_once(
                uid="inbox-user", kind="task_failed", source_id="inbox-task-2", title="另一任务失败"
            )
            await db.commit()

        assert duplicate.id == first_id
        assert duplicate.title == "首次失败"
        assert other_kind.id != first_id
        assert other_source.id != first_id
        async with scoped_engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM user_inbox_items")) == 3
    finally:
        await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
