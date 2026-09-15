"""验证本地候选过滤不隐藏已结束任务，也不改变其他候选的顺序。"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from arq.worker import Worker
from yuxi.services.arq_worker import YuxiWorker


@pytest.mark.asyncio
async def test_only_live_local_tasks_are_filtered(monkeypatch):
    """仅存在于本地且未结束的 Task 可跳过；结束、取消及远端候选仍参与领取。"""
    loop = asyncio.get_running_loop()
    live, done, cancelled = [loop.create_future() for _ in range(3)]
    done.set_result(None)
    cancelled.cancel()
    worker = object.__new__(YuxiWorker)
    worker.tasks = {"live": live, "done": done, "cancelled": cancelled}
    parent = AsyncMock()
    monkeypatch.setattr(Worker, "start_jobs", parent)
    try:
        await worker.start_jobs([b"live", b"remote", b"done", b"cancelled", b"new"])
        assert parent.call_args.args[0] == [b"remote", b"done", b"cancelled", b"new"]
    finally:
        live.cancel()
