"""验证矩阵统计不会混入客户端时间或相邻用户结果。"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from test.performance.probe import ApiProbe
from test.performance.matrix import (
    AgentLoadClient,
    cancel_failed_request,
    channel_rounds,
    join_timings,
    main,
    percentile,
    record_group,
    run_channel,
    run_request,
    stages_complete,
    summarize_timings,
    verified_completed,
)


class MatrixTimingTest(unittest.TestCase):
    """检查精确关联、缺失与小样本分位数。"""

    def test_http_success_without_owned_output_is_not_verified(self):
        """HTTP/SSE 成功不能替代数据库最终事实。"""
        row = {
            "success": True,
            "db": {"status": "completed", "attempts": 1, "bound_output": True},
        }
        self.assertTrue(verified_completed(row))
        for field, value in (
            ("status", "running"),
            ("attempts", 2),
            ("bound_output", False),
        ):
            self.assertFalse(verified_completed({**row, "db": {**row["db"], field: value}}))
        self.assertFalse(verified_completed({"success": True}))

    def test_formal_budget_and_explicit_small_experiment(self):
        """固定预算不暗中添加预热，轮数覆盖不得放大成每通道总样本数。"""
        levels = [1, 10, 20, 50, 100]
        self.assertEqual([channel_rounds(c) for c in levels], [100, 10, 5, 5, 5])
        self.assertEqual(sum(c * channel_rounds(c) for c in levels) * 3, 3150)
        self.assertEqual(channel_rounds(20, 2), 2)
        with self.assertRaises(ValueError):
            channel_rounds(1, 0)

    def test_complete_requires_api_and_worker_chunks(self):
        """只有 worker 已输出，或相邻 API 已输出，都不能冒充本请求完整。"""
        requests = [{"request_id": "a", "run_id": "r"}]
        events = [
            {"event": "stages_done", "run_id": "r"},
            {"event": "stages_done", "request_id": "other"},
        ]
        self.assertFalse(stages_complete(requests, events))
        events.append({"event": "stages_done", "request_id": "a"})
        self.assertTrue(stages_complete(requests, events))

    def test_server_boundary_and_missing(self):
        rows = [
            {"request_id": "a", "uid": "u", "run_id": "r"},
            {"request_id": "b", "uid": "v"},
        ]
        events = [
            {"event": "api_received", "request_id": "a", "time_ns": 1000000},
            {
                "event": "model_send",
                "run_id": "r",
                "time_ns": 4000000,
                "container": "worker-1",
                "spans": [],
            },
        ]
        joined = join_timings(rows, events, [])
        self.assertEqual(joined[0]["api_to_model_ms"], 3)
        self.assertIsNone(joined[1]["api_to_model_ms"])
        self.assertIsNone(percentile([None], 0.95))
        self.assertEqual(percentile(list(range(1, 51)), 0.95), 48)

    def test_wrong_user_rejected(self):
        with self.assertRaisesRegex(ValueError, "串绑"):
            join_timings(
                [{"request_id": "a", "uid": "u", "run_id": "r"}],
                [],
                [{"id": "r", "request_id": "a", "uid": "other"}],
            )

    def test_late_stage_chunks_join_only_their_request_and_run(self):
        """SSE 结束后输出的分块也必须回到同一 Request/Run。"""
        rows = [{"request_id": "a", "uid": "u", "run_id": "r"}]
        events = [
            {"event": "stage_spans", "request_id": "a", "spans": [{"id": 1}]},
            {"event": "stage_spans", "run_id": "r", "spans": [{"id": 2}]},
            {"event": "stage_spans", "run_id": "other", "spans": [{"id": 99}]},
            {"event": "stage_spans", "run_id": "r", "spans": [{"id": 3}]},
        ]
        joined = join_timings(rows, events, [])
        self.assertEqual(joined[0]["api_spans"], [{"id": 1}])
        self.assertEqual(joined[0]["spans"], [{"id": 2}, {"id": 3}])

    def test_wrong_request_rejected(self):
        with self.assertRaisesRegex(ValueError, "串绑"):
            join_timings(
                [{"request_id": "a", "uid": "u", "run_id": "r"}],
                [],
                [{"id": "r", "request_id": "other", "uid": "u"}],
            )

    def test_database_stages_survive_missing_model_probe(self):
        """没有发送模型的失败请求，仍保留已经经历的数据库阶段。"""
        row = {"request_id": "a", "uid": "u", "run_id": "r"}
        stored = {
            "id": "r",
            "request_id": "a",
            "uid": "u",
            "created_at": "1970-01-01T00:00:00.002",
            "started_at": "1970-01-01T00:00:00.005",
            "prepared_at": "1970-01-01T00:00:00.009",
        }
        for events in (
            [],
            [{"event": "api_received", "request_id": "a", "time_ns": 1000000}],
        ):
            with self.subTest(events=events):
                joined = join_timings([row.copy()], events, [stored])[0]
                self.assertEqual(joined["created_to_started_ms"], 3)
                self.assertEqual(joined["started_to_prepared_ms"], 4)
                self.assertIsNone(joined["prepared_to_model_ms"])
                self.assertIsNone(joined["api_to_model_ms"])


class ApiBoundaryTest(unittest.IsolatedAsyncioTestCase):
    """API 入口必须先于应用内部鉴权和正文读取。"""

    async def test_api_timestamp_precedes_app(self):
        observed = []

        async def app(scope, receive, send):
            """用业务处理开始验证探针的装配顺序。"""
            self.assertEqual(observed[0]["time_ns"], 123)
            self.assertEqual(observed[0]["request_id"], "matrix-test")

        with (
            patch(
                "test.performance.probe.time.time_ns",
                return_value=123,
            ),
            patch(
                "test.performance.probe.emit",
                side_effect=observed.append,
            ),
        ):
            await ApiProbe(app)(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/api/agent/runs",
                    "headers": [(b"x-load-test-id", b"matrix-test")],
                },
                None,
                None,
            )


class ContinuousChannelsTest(unittest.IsolatedAsyncioTestCase):
    """固定 Thread 内串行，快通道不等待慢通道，也不额外补发失败请求。"""

    async def test_existing_results_stop_before_authentication(self):
        """保留已有付费样本，不在误用输出目录时开始新实验。"""
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            result = output_dir / "matrix.json"
            result.write_text('{"preserved": true}\n')
            args = SimpleNamespace(rounds_per_thread=None, concurrency=[1], output_dir=output_dir)
            with (
                patch.dict(
                    "os.environ",
                    {
                        "COMPOSE_PROJECT_NAME": "yuxi-alpha",
                        "YUXI_STATE_DIR": "../.yuxi/slots/alpha",
                    },
                ),
                patch("test.performance.matrix.authenticate") as authenticate,
                self.assertRaisesRegex(FileExistsError, "保留付费样本"),
            ):
                await main(args)
            authenticate.assert_not_called()
            self.assertEqual(result.read_text(), '{"preserved": true}\n')

    async def test_fast_channel_finishes_five_turns_while_slow_one_waits(self):
        slow_started, release_slow = asyncio.Event(), asyncio.Event()
        calls = []
        active = set()

        async def fake_request(load, slug, thread, request, uid, *, row=None):
            """用事件制造慢通道并验证同一通道无重叠。"""
            self.assertNotIn(uid, active)
            active.add(uid)
            calls.append((uid, thread, request))
            if uid == "slow":
                slow_started.set()
                await release_slow.wait()
            await asyncio.sleep(0)
            active.remove(uid)
            return {"success": True}

        with patch("test.performance.matrix.run_request", side_effect=fake_request):
            slow = asyncio.create_task(run_channel((None, "a", "slow-thread", "matrix-slow", "slow"), 5, 0))
            try:
                await slow_started.wait()
                fast_rows = await asyncio.wait_for(
                    run_channel((None, "a", "fast-thread", "matrix-fast", "fast"), 5, 1),
                    1,
                )
                self.assertEqual([r["turn"] for r in fast_rows], [1, 2, 3, 4, 5])
                self.assertFalse(slow.done())
                self.assertEqual(len(calls), 6)
                release_slow.set()
                self.assertEqual(len(await slow), 5)
            finally:
                slow.cancel()
                await asyncio.gather(slow, return_exceptions=True)
        self.assertEqual(len({call[2] for call in calls}), 10)
        self.assertTrue(all(thread == uid + "-thread" for uid, thread, _ in calls))

    async def test_failed_turn_stops_channel_without_replacement(self):
        async def failed(*args, **kwargs):
            """失败必须保留且不继续污染同一 Thread 的历史。"""
            return {"success": False}

        with patch("test.performance.matrix.run_request", side_effect=failed):
            rows = await run_channel((None, "a", "t", "matrix-first", "u"), 5, 0)
        self.assertEqual(rows, [{"success": False, "channel": 0, "turn": 1}])

    async def test_client_ttft_uses_submission_clock(self):
        class Client:
            """验证订阅 SSE 使用请求提交时点而非订阅开始时点。"""

            timeout_seconds = 1

            def __init__(self):
                """每个测试通道拥有独立请求头。"""
                self.headers = {}

            async def submit_run(self, **kwargs):
                return {"run_id": "r"}, 20

            async def consume_run_events(self, run_id, submitted_at):
                self.observed_start = submitted_at
                return {}, None, 30, 40, 50

            async def get_run_result(self, run_id):
                return {
                    "request_id": "matrix-r",
                    "agent_run_id": "r",
                    "status": "completed",
                    "output": "hi",
                }

        client = Client()
        with patch("test.performance.matrix.time.perf_counter", side_effect=[10, 10.1]):
            row = await run_request(client, "a", "t", "matrix-r", "u")
        self.assertTrue(row["success"])
        self.assertEqual(client.observed_start, 10)
        self.assertEqual(row["client_first_token_ms"], 40)
        self.assertAlmostEqual(row["client_total_ms"], 100)

    async def test_failed_cancellation_does_not_cancel_other_channels(self):
        """取消网络故障只记录在失败通道，其他通道仍完成五轮。"""

        def transport(request):
            """构造可复现的取消网络故障。"""
            raise httpx.ConnectError("offline", request=request)

        async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(transport)) as client:
            failed = AgentLoadClient(client, {}, 1)
            failed.submit_run = AsyncMock(side_effect=RuntimeError("submit failed"))
            healthy = AgentLoadClient(client, {}, 1)

            async def submit(**kwargs):
                """将每一轮请求绑定到该轮的结果。"""
                healthy.get_run_result = AsyncMock(
                    return_value={
                        "request_id": kwargs["request_id"],
                        "agent_run_id": "r",
                        "status": "completed",
                        "output": "hi",
                    }
                )
                return {"run_id": "r"}, 1

            healthy.submit_run = submit
            healthy.consume_run_events = AsyncMock(return_value=({}, None, 1, 2, 3))
            async with asyncio.TaskGroup() as tasks:
                bad = tasks.create_task(run_channel((failed, "a", "bad", "req-bad", "bad"), 5, 0))
                good = tasks.create_task(run_channel((healthy, "a", "good", "req-good", "good"), 5, 1))
        self.assertEqual(len(good.result()), 5)
        self.assertTrue(all(row["success"] for row in good.result()))
        self.assertEqual(len(bad.result()), 1)
        self.assertEqual(bad.result()[0]["error"], "RuntimeError")
        self.assertEqual(bad.result()[0]["cancel_error"], "ConnectError")

    async def test_lost_submit_response_resolves_exact_dispatched_run_and_waits(self):
        """提交响应丢失后，409 提供的精确 Run 必须取消并回读终态。"""
        run_id = "00000000-0000-0000-0000-000000000001"
        calls = []
        statuses = iter(["running", "cancelled"])

        def transport(request):
            """第一次结果仍在运行，不能据取消接口的 200 提前结束。"""
            calls.append((request.method, request.url.path))
            if request.url.path == "/api/agent/requests/req/cancel":
                return httpx.Response(
                    409,
                    json={
                        "detail": {
                            "code": "request_already_dispatched",
                            "run_id": run_id,
                        }
                    },
                )
            if request.url.path == f"/api/agent/runs/{run_id}/cancel":
                return httpx.Response(200, json={"status": "running"})
            self.assertEqual(request.url.path, f"/api/agent/runs/{run_id}/result")
            return httpx.Response(
                200,
                json={
                    "request_id": "req",
                    "agent_run_id": run_id,
                    "status": next(statuses),
                },
            )

        row = {"request_id": "req", "run_id": None}
        async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(transport)) as client:
            await cancel_failed_request(AgentLoadClient(client, {}, 1), row)
        self.assertEqual(row["run_id"], run_id)
        self.assertTrue(row["cancel_confirmed"])
        self.assertEqual([method for method, _ in calls], ["POST", "POST", "GET", "GET"])

    async def test_cancelled_channel_cleans_up_and_propagates_cancellation(self):
        """任务取消也先触发精确清理，并保留 asyncio 的取消语义。"""
        client = AsyncMock()
        client.headers = {}
        client.timeout_seconds = 1
        client.submit_run.side_effect = asyncio.CancelledError()
        with (
            patch(
                "test.performance.matrix.cancel_failed_request",
                new_callable=AsyncMock,
            ) as cleanup,
            self.assertRaises(asyncio.CancelledError),
        ):
            await run_request(client, "a", "t", "req", "u")
        self.assertEqual(cleanup.call_args.args[1]["request_id"], "req")


class ObservationPersistenceTest(unittest.IsolatedAsyncioTestCase):
    """探针失败不能丢弃已经完成的付费请求。"""

    async def test_main_interruption_saves_paid_and_inflight_rows_before_safe_cleanup(self):
        """主入口取消或通道异常保留本组证据，未确认终态时不删除用户与会话。"""
        for confirmed, failure in ((False, "cancel"), (True, "cancel"), (False, "exception")):
            with self.subTest(confirmed=confirmed, failure=failure), tempfile.TemporaryDirectory() as directory:
                deletions, submitted = [], {}
                inflight = asyncio.Event()

                def respond(request):
                    """只实现本用例的身份与会话协议，记录实际 DELETE。"""
                    if request.method == "DELETE":
                        deletions.append(request.url.path)
                        return httpx.Response(200, json={})
                    if request.url.path == "/api/auth/users":
                        return httpx.Response(200, json={"id": 1, "uid": "u"})
                    if request.url.path == "/api/auth/impersonate/1":
                        return httpx.Response(200, json={"access_token": "test-token"})
                    if request.url.path == "/api/chat/thread":
                        return httpx.Response(200, json={"id": "t"})
                    raise AssertionError(request.url.path)

                async def submit(load, **kwargs):
                    """分别构造已经完成和正在运行的精确请求。"""
                    run_id = f"r{len(submitted) + 1}"
                    submitted[run_id] = kwargs["request_id"]
                    return {"run_id": run_id}, 1

                async def consume(load, run_id, started):
                    """第一轮完成，第二轮保留在途或模拟协议异常。"""
                    if run_id == "r2":
                        inflight.set()
                        if failure == "exception":
                            raise KeyError("broken protocol")
                        await asyncio.Future()
                    return {}, None, 1, 2, 3

                async def result(load, run_id):
                    """返回同一 Request/Run 的完成结果。"""
                    return {
                        "request_id": submitted[run_id],
                        "agent_run_id": run_id,
                        "status": "completed",
                        "output": "hi",
                    }

                async def cancel(load, row):
                    """显式区分已确认与未确认终态，不冒充取消成功。"""
                    row["cancel_confirmed"] = confirmed

                client = httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(respond))
                args = SimpleNamespace(
                    base_url="http://test",
                    agent_slug="a",
                    workers=[1],
                    concurrency=[1],
                    rounds_per_thread=5,
                    output_dir=Path(directory),
                )
                with (
                    patch.dict(
                        "os.environ", {"COMPOSE_PROJECT_NAME": "yuxi-alpha", "YUXI_STATE_DIR": "../.yuxi/slots/alpha"}
                    ),
                    patch("test.performance.matrix.httpx.AsyncClient", return_value=client),
                    patch("test.performance.matrix.authenticate", new=AsyncMock(return_value={})),
                    patch("test.performance.matrix.resolve_agent_slug", new=AsyncMock(return_value="a")),
                    patch("test.performance.matrix.command", return_value=""),
                    patch(
                        "test.performance.matrix.read_probe_events",
                        return_value=[{"event": "worker_ready", "container": "w"}],
                    ),
                    patch.object(AgentLoadClient, "submit_run", submit),
                    patch.object(AgentLoadClient, "consume_run_events", consume),
                    patch.object(AgentLoadClient, "get_run_result", result),
                    patch("test.performance.matrix.cancel_failed_request", cancel),
                ):
                    task = asyncio.create_task(main(args))
                    try:
                        await asyncio.wait_for(inflight.wait(), 2)
                        if failure == "cancel":
                            task.cancel()
                        with self.assertRaises(asyncio.CancelledError if failure == "cancel" else ExceptionGroup):
                            await asyncio.wait_for(task, 2)
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                group = json.loads((Path(directory) / "matrix.json").read_text())["groups"][0]
                self.assertEqual((group["planned_requests"], group["actual_requests"]), (5, 2))
                self.assertEqual([r["run_id"] for r in group["requests"]], ["r1", "r2"])
                self.assertTrue(group["requests"][0]["success"])
                self.assertEqual(group["requests"][1]["cancel_confirmed"], confirmed)
                self.assertIn("client_total_ms", group["requests"][1])
                if confirmed:
                    self.assertEqual(len(deletions), 2)
                else:
                    self.assertEqual(deletions, [])
                    self.assertEqual(group["unconfirmed_terminal"], 1)

    async def test_incomplete_probes_save_rows_and_known_stages_before_raising(self):
        report = {"groups": [], "rounds_per_thread": 5}
        group = {
            "warmup": False,
            "rounds_per_thread": 5,
            "requests": [
                {
                    "request_id": "req",
                    "uid": "u",
                    "run_id": "r",
                    "success": True,
                    "turn": 1,
                }
            ],
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict("os.environ", {"MATRIX_FINE_TIMING": "1"}),
            patch("test.performance.matrix.read_probe_events", return_value=[]),
            patch("test.performance.matrix.read_runs", return_value=[]),
            patch("test.performance.matrix.asyncio.sleep", new_callable=AsyncMock),
        ):
            path = Path(directory) / "matrix.json"
            with self.assertRaisesRegex(RuntimeError, "已保存样本"):
                await record_group(report, group, path, "start")
            saved = json.loads(path.read_text())["groups"][0]
        self.assertEqual(saved["requests"][0]["request_id"], "req")
        self.assertTrue(saved["requests"][0]["success"])
        self.assertFalse(saved["stages_complete"])
        self.assertEqual(saved["observation_error"], "RuntimeError")
        self.assertEqual(saved["timings"]["api_to_model_ms"]["n"], 0)


class TimingDimensionsTest(unittest.TestCase):
    """多维汇总必须保留有效样本数，不把缺失值变成零。"""

    def test_metrics_include_missing_count_and_distinct_boundaries(self):
        result = summarize_timings([{"api_to_model_ms": 10, "client_total_ms": 80}, {"api_to_model_ms": 30}])
        self.assertEqual(result["api_to_model_ms"], {"n": 2, "p50": 10, "p95": 30})
        self.assertEqual(result["client_total_ms"], {"n": 1, "p50": 80, "p95": 80})
        self.assertEqual(result["api_to_finished_ms"], {"n": 0, "p50": None, "p95": None})
