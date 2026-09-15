from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from yuxi.storage.postgres import manager as manager_module
from yuxi.storage.postgres.manager import PostgresManager


def test_langgraph_pool_checks_connections_before_checkout(monkeypatch):
    """Checkpoint 连接池必须淘汰 PostgreSQL 重启后留下的坏连接。"""
    captured = {}

    class Pool:
        @staticmethod
        async def check_connection(_connection):
            return None

        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://user:pass@postgres/yuxi")
    monkeypatch.setattr(manager_module, "AsyncConnectionPool", Pool)
    monkeypatch.setattr(manager_module, "create_async_engine", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(manager_module, "async_sessionmaker", lambda **_kwargs: object())

    manager = object.__new__(PostgresManager)
    manager.__init__()

    manager.initialize()

    assert captured["check"] is Pool.check_connection


def test_postgres_pool_capacity_uses_environment(monkeypatch):
    """SQLAlchemy 与 LangGraph 连接池容量必须由部署配置拥有。"""
    engine_options = {}
    pool_options = {}

    class Pool:
        @staticmethod
        async def check_connection(_connection):
            return None

        def __init__(self, **kwargs):
            pool_options.update(kwargs)

    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://user:pass@postgres/yuxi")
    monkeypatch.setenv("POSTGRES_POOL_SIZE", "120")
    monkeypatch.setenv("POSTGRES_MAX_OVERFLOW", "30")
    monkeypatch.setenv("POSTGRES_POOL_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("LANGGRAPH_POSTGRES_POOL_SIZE", "60")
    monkeypatch.setenv("LANGGRAPH_POSTGRES_POOL_TIMEOUT_SECONDS", "60")
    monkeypatch.setattr(
        manager_module,
        "create_async_engine",
        lambda *_args, **kwargs: engine_options.update(kwargs) or object(),
    )
    monkeypatch.setattr(manager_module, "AsyncConnectionPool", Pool)
    monkeypatch.setattr(manager_module, "async_sessionmaker", lambda **_kwargs: object())

    manager = object.__new__(PostgresManager)
    manager.__init__()
    manager.initialize()

    assert engine_options["pool_size"] == 120
    assert engine_options["max_overflow"] == 30
    assert engine_options["pool_timeout"] == 60
    assert pool_options["max_size"] == 60
    assert pool_options["timeout"] == 60


@pytest.mark.asyncio
async def test_langgraph_setup_uses_cross_process_advisory_lock():
    """官方 checkpoint migration 必须被 PostgreSQL advisory lock 包围。"""
    manager = object.__new__(PostgresManager)
    manager._initialized = True
    manager._langgraph_checkpointer_setup = False
    statements = []

    class Connection:
        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(fetchone=_true_row)

    @asynccontextmanager
    async def connection():
        yield Connection()

    async def setup():
        statements.append("setup")

    saver = SimpleNamespace(setup=setup)
    manager.langgraph_pool = SimpleNamespace(connection=connection)
    manager.langgraph_checkpointer = saver

    assert await manager.setup_langgraph_checkpointer() is saver
    assert statements == [
        "SELECT pg_advisory_lock(94721802)",
        "setup",
        "SELECT pg_advisory_unlock(94721802)",
    ]


@pytest.mark.asyncio
async def test_langgraph_setup_discards_connection_when_unlock_fails():
    """无法确认 advisory lock 已释放时不能把持锁 session 放回池中。"""
    manager = object.__new__(PostgresManager)
    manager._initialized = True
    manager._langgraph_checkpointer_setup = False
    connection_closed = False

    class Connection:
        async def execute(self, statement):
            if "unlock" in statement:
                raise RuntimeError("unlock failed")
            return SimpleNamespace(fetchone=_true_row)

        async def close(self):
            nonlocal connection_closed
            connection_closed = True

    @asynccontextmanager
    async def connection():
        yield Connection()

    manager.langgraph_pool = SimpleNamespace(connection=connection)
    manager.langgraph_checkpointer = SimpleNamespace(setup=_noop)

    with pytest.raises(RuntimeError, match="unlock failed"):
        await manager.setup_langgraph_checkpointer()

    assert connection_closed is True
    assert manager._langgraph_checkpointer_setup is False


async def _true_row():
    return (True,)


async def _noop():
    return None
