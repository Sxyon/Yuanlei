"""验证细粒度诊断的等待/执行切片归属和原始异常语义。"""

import asyncio
import contextvars
import time
import unittest

from test.performance.stage_probe import measured


class StageProbeTest(unittest.IsolatedAsyncioTestCase):
    """等待者不应获得其他任务消耗的 CPU 时间。"""

    async def test_other_task_cpu_not_charged_to_waiter(self):
        trace = contextvars.ContextVar("test_stage", default=None)
        state = {"spans": [], "sent": False}
        trace.set(state)
        ready = asyncio.Event()

        async def wait():
            """等待另一个任务执行 CPU 工作。"""
            await ready.wait()
            return 42

        task = asyncio.create_task(measured(wait, trace)())
        await asyncio.sleep(0)
        until = time.thread_time() + 0.04
        while time.thread_time() < until:
            pass
        ready.set()
        self.assertEqual(await task, 42)
        span = state["spans"][0]
        self.assertGreater(span["ms"], 35)
        self.assertLess(span["cpu_ms"], span["ms"] / 4)
        self.assertGreaterEqual(span["resumes"], 2)

    async def test_cancellation_and_exception_propagate(self):
        trace = contextvars.ContextVar("test_cancel", default=None)
        trace.set({"spans": [], "sent": False})
        closed = []

        async def wait():
            """取消必须执行原协程的 finally。"""
            try:
                await asyncio.Event().wait()
            finally:
                closed.append(True)

        task = asyncio.create_task(measured(wait, trace)())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(closed, [True])

        async def fail():
            """异常不应被计时包装吞掉。"""
            raise ValueError("expected")

        with self.assertRaisesRegex(ValueError, "expected"):
            await measured(fail, trace)()

    async def test_cpu_stops_at_first_model_send_even_within_one_slice(self):
        """同一执行切片跨越发送边界时，也不能把模型发送后的 CPU 算进去。"""
        trace = contextvars.ContextVar("test_cutoff", default=None)
        state = {"spans": [], "sent": False}
        trace.set(state)

        async def send():
            """模拟在一个切片中触及发送边界并继续执行。"""
            state.update(
                stop_perf_ns=time.perf_counter_ns(),
                stop_cpu_ns=time.thread_time_ns(),
                sent=True,
            )
            until = time.thread_time() + 0.03
            while time.thread_time() < until:
                pass
            await asyncio.sleep(0)
            return 42

        self.assertEqual(await measured(send, trace)(), 42)
        span = state["spans"][0]
        self.assertGreater(span["ms"], 25)
        self.assertLess(span["cpu_ms"], 5)
        self.assertEqual(span["resumes"], 1)
