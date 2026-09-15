"""用独立 Redis 队列证明本地过滤保留竞争、完成和重试，不调用模型。"""

import asyncio
import uuid

import pytest
import pytest_asyncio
from arq import create_pool
from arq.constants import in_progress_key_prefix
from arq.worker import Retry, Worker
from yuxi.services.arq_worker import YuxiWorker
from yuxi.storage.redis import get_arq_redis_settings

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def record_result(ctx, label):
    """慢任务等待显式释放，完成事实写入本测试独占的 Redis 列表。"""
    if label == "slow":
        ctx["started"].set()
        await ctx["release"].wait()
    await ctx["redis"].rpush(ctx["results_key"], label)
    return label


async def retry_once(ctx):
    """首轮主动重试或等待取消，第二轮返回实际 attempt 编号。"""
    attempt = ctx["job_try"]
    await ctx["redis"].rpush(ctx["results_key"], f"attempt-{attempt}")
    if attempt == 1:
        if ctx["cancel_first"]:
            ctx["started"].set()
            await ctx["release"].wait()
        else:
            raise Retry(defer=0)
    return attempt


@pytest_asyncio.fixture
async def isolated_queue():
    """只清理随机命名空间内本测试创建的队列、任务与结果。"""
    redis = await create_pool(get_arq_redis_settings())
    namespace = f"pytest-worker-{uuid.uuid4().hex}"
    queue_name = f"arq:{namespace}:queue"
    workers = []
    try:
        yield redis, namespace, queue_name, workers
    finally:
        tasks = [task for worker in workers for task in worker.tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
        keys = [key async for key in redis.scan_iter(match=f"*{namespace}*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()


def make_worker(state, worker_class=YuxiWorker, *, cancel_first=False):
    """使用真实 ARQ 执行器，运行时控制与键空间局限于本测试。"""
    redis, namespace, queue_name, workers = state
    worker = worker_class(
        functions=[record_result, retry_once],
        redis_pool=redis,
        queue_name=queue_name,
        health_check_key=f"arq:{namespace}:health",
        handle_signals=False,
        max_jobs=20,
        ctx={
            "redis": redis,
            "results_key": f"arq:{namespace}:results",
            "started": asyncio.Event(),
            "release": asyncio.Event(),
            "cancel_first": cancel_first,
        },
    )
    workers.append(worker)
    return worker


@pytest.mark.parametrize("worker_class", [Worker, YuxiWorker])
async def test_refill_avoids_redis_for_local_running_job(isolated_queue, monkeypatch, worker_class):
    """原实现触发精确旧任务 guard；优化实现可在旧任务未完成时完成新任务。"""
    redis, namespace, queue_name, _ = isolated_queue
    worker = make_worker(isolated_queue, worker_class)
    old_id, new_id = f"{namespace}-old", f"{namespace}-new"
    old_job = await redis.enqueue_job("record_result", "slow", _queue_name=queue_name, _job_id=old_id)
    await asyncio.wait_for(worker._poll_iteration(), timeout=3)
    await asyncio.wait_for(worker.ctx["started"].wait(), timeout=3)
    new_job = await redis.enqueue_job("record_result", "fast", _queue_name=queue_name, _job_id=new_id)
    original_pipeline = redis.pipeline

    def guarded_pipeline(*args, **kwargs):
        """只拦截已经由本进程执行的精确任务，其他 Redis 操作仍真实执行。"""
        pipeline = original_pipeline(*args, **kwargs)
        original_watch = pipeline.watch

        async def watch(*names):
            """重复旧任务检查必须在正确原因上失败。"""
            assert in_progress_key_prefix + old_id not in names, "重复检查本地运行任务"
            return await original_watch(*names)

        pipeline.watch = watch
        return pipeline

    monkeypatch.setattr(redis, "pipeline", guarded_pipeline)
    if worker_class is Worker:
        with pytest.raises(AssertionError, match="重复检查本地运行任务"):
            await asyncio.wait_for(worker._poll_iteration(), timeout=3)
        return

    await asyncio.wait_for(worker._poll_iteration(), timeout=3)
    assert await new_job.result(timeout=3, poll_delay=0.01) == "fast"
    assert not worker.tasks[old_id].done()
    assert await redis.lrange(worker.ctx["results_key"], 0, -1) == [b"fast"]
    worker.ctx["release"].set()
    assert await old_job.result(timeout=3, poll_delay=0.01) == "slow"
    assert await redis.lrange(worker.ctx["results_key"], 0, -1) == [b"fast", b"slow"]


async def test_two_workers_still_have_one_winner(isolated_queue):
    """跨 Worker 同时看到候选时，真实 Redis 竞争仍只执行一次。"""
    redis, namespace, queue_name, _ = isolated_queue
    workers = [make_worker(isolated_queue), make_worker(isolated_queue)]
    job_id = f"{namespace}-race"
    job = await redis.enqueue_job("record_result", "slow", _queue_name=queue_name, _job_id=job_id)
    await asyncio.wait_for(asyncio.gather(*(worker.start_jobs([job_id.encode()]) for worker in workers)), timeout=3)
    winners = [worker for worker in workers if job_id in worker.tasks]
    assert len(winners) == 1
    winner = winners[0]
    await asyncio.wait_for(winner.ctx["started"].wait(), timeout=3)
    assert await redis.lrange(winner.ctx["results_key"], 0, -1) == []
    winner.ctx["release"].set()
    assert await job.result(timeout=3, poll_delay=0.01) == "slow"
    assert await redis.lrange(winner.ctx["results_key"], 0, -1) == [b"slow"]


@pytest.mark.parametrize("cancel_first", [False, True])
async def test_finished_task_can_be_retried_before_poll_cleanup(isolated_queue, cancel_first):
    """已结束的本地 Task 即使仍在 tasks 字典中，也不能挡住 Retry 或取消后的重试。"""
    redis, namespace, queue_name, _ = isolated_queue
    worker = make_worker(isolated_queue, cancel_first=cancel_first)
    job_id = f"{namespace}-retry"
    job = await redis.enqueue_job("retry_once", _queue_name=queue_name, _job_id=job_id)
    await asyncio.wait_for(worker.start_jobs([job_id.encode()]), timeout=3)
    if cancel_first:
        await asyncio.wait_for(worker.ctx["started"].wait(), timeout=3)
        worker.tasks[job_id].cancel()
    await asyncio.wait_for(worker.tasks[job_id], timeout=3)
    assert worker.tasks[job_id].done()
    assert await redis.zscore(queue_name, job_id) is not None
    await asyncio.wait_for(worker.start_jobs([job_id.encode()]), timeout=3)
    assert await job.result(timeout=3, poll_delay=0.01) == 2
    assert await redis.lrange(worker.ctx["results_key"], 0, -1) == [b"attempt-1", b"attempt-2"]
