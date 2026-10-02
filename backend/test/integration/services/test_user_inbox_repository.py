"""用户收件箱通知幂等写入的真实 PostgreSQL 测试。"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


@pytest_asyncio.fixture
async def inbox_schema() -> AsyncGenerator[tuple[async_sessionmaker, object, object], None]:
    """为单个用例建立只含业务表的隔离 Schema，退出时整库回收。"""
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
        yield async_sessionmaker(scoped_engine, expire_on_commit=False), scoped_engine, admin_engine
    finally:
        await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def test_add_once_conflict_returns_existing_notification(inbox_schema):
    """同一 (uid, kind, source_id) 重复写入命中唯一键时返回既有行，不同维度各自成行。"""
    sessions, scoped_engine, _admin_engine = inbox_schema

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


async def test_add_once_concurrent_duplicate_does_not_raise(inbox_schema):
    """首个事务未提交时并发写入同一键，第二个写入等待后返回既有行且不抛 IntegrityError。"""
    sessions, scoped_engine, admin_engine = inbox_schema

    holder: dict[str, int] = {}
    first_session: AsyncSession = sessions()
    try:
        first = await UserInboxRepository(first_session).add_once(
            uid="inbox-user", kind="task_failed", source_id="inbox-task", title="并发首次"
        )

        async def insert_duplicate() -> object:
            async with sessions() as second:
                holder["pid"] = await second.scalar(text("SELECT pg_backend_pid()"))
                row = await UserInboxRepository(second).add_once(
                    uid="inbox-user", kind="task_failed", source_id="inbox-task", title="并发重复"
                )
                await second.commit()
                return row

        task = asyncio.create_task(insert_duplicate())
        wait_event = None
        for _ in range(100):
            pid = holder.get("pid")
            if pid:
                async with admin_engine.connect() as observer:
                    wait_event = await observer.scalar(
                        text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid}
                    )
                if wait_event == "Lock":
                    break
            await asyncio.sleep(0.02)
        assert wait_event == "Lock", "第二个写入应先等待第一个未提交的唯一键"

        await first_session.commit()
        duplicate = await task
        assert duplicate.id == first.id
    finally:
        await first_session.close()

    async with scoped_engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM user_inbox_items")) == 1
