"""Agent 压测脚本的纯逻辑与协议负向测试。"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import httpx

from test.performance.__main__ import build_parser
from test.performance.load import (
    AgentLoadClient,
    LoadTestError,
    LocalResourceSampler,
    TaskResult,
    ToolEvidence,
    _parse_memory_mb,
    contains_model_output,
    evaluate_result,
    first_model_request_latency_ms,
    iter_sse,
    observe_tool_evidence,
    parse_concurrency,
    record_run_timing,
    summarize,
    write_results,
)


async def _lines(*items: str):
    for item in items:
        yield item


class AgentLoadTestScriptTest(unittest.IsolatedAsyncioTestCase):
    """验证脚本不会把错误协议或缺失工具执行误报为成功。"""

    async def test_iter_sse_parses_json_and_ignores_heartbeat(self) -> None:
        events = [
            event
            async for event in iter_sse(
                _lines(
                    ": heartbeat",
                    "",
                    "id: 1-0",
                    "event: run_created",
                    'data: {"request_id":"request-1",',
                    'data: "run_id":"run-1"}',
                    "",
                )
            )
        ]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "run_created")
        self.assertEqual(events[0].event_id, "1-0")
        self.assertEqual(events[0].data["run_id"], "run-1")

    async def test_iter_sse_rejects_non_json_data(self) -> None:
        with self.assertRaises(LoadTestError):
            async for _ in iter_sse(_lines("event: end", "data: not-json", "")):
                pass

    async def test_request_sse_returns_its_run_created_id(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/agent/requests/request-1/events")
            return httpx.Response(
                200,
                text=(
                    'event: queued\ndata: {"request_id":"request-1","position":1}\n\n'
                    'event: run_created\ndata: {"request_id":"request-1","run_id":"run-1"}\n\n'
                ),
            )

        async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            load_client = AgentLoadClient(client, {}, 10)
            run_id = await load_client.wait_for_run_id(
                "request-1",
                "/api/agent/requests/request-1/events",
            )

        self.assertEqual(run_id, "run-1")

    async def test_request_sse_rejects_neighbor_request(self) -> None:
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text='event: run_created\ndata: {"request_id":"request-2","run_id":"run-2"}\n\n',
            )

        async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            load_client = AgentLoadClient(client, {}, 10)
            with self.assertRaises(LoadTestError):
                await load_client.wait_for_run_id(
                    "request-1",
                    "/api/agent/requests/request-1/events",
                )

    def test_sandbox_result_requires_execute_completion_marker(self) -> None:
        payload = {
            "status": "completed",
            "request_id": "request-1",
            "agent_run_id": "run-1",
            "output": "LOAD_TEST_OK",
        }

        success, error, _ = evaluate_result(
            scenario="sandbox",
            payload=payload,
            request_id="request-1",
            run_id="run-1",
            evidence=ToolEvidence(execute_started=True, execute_finished=True, output_marker_seen=False),
        )

        self.assertFalse(success)
        self.assertIn("LOAD_TEST_TOOL_OK", error or "")

    def test_compact_tool_message_proves_execute_completion(self) -> None:
        evidence = ToolEvidence(execute_started=True)

        observe_tool_evidence(
            {"payload": {"chunk": {"msg": {"type": "tool", "content": "LOAD_TEST_TOOL_OK\n"}}}},
            evidence,
        )

        self.assertTrue(evidence.execute_finished)
        self.assertTrue(evidence.output_marker_seen)

    def test_first_model_output_accepts_text_and_tool_call_delta(self) -> None:
        self.assertTrue(
            contains_model_output(
                {"payload": {"items": [{"stream_event": {"type": "message_delta", "content": "你"}}]}}
            )
        )
        self.assertTrue(
            contains_model_output(
                {
                    "payload": {
                        "items": [
                            {
                                "stream_event": {
                                    "type": "tool_call_delta",
                                    "args_delta": "{",
                                }
                            }
                        ]
                    }
                }
            )
        )

    def test_metadata_does_not_count_as_first_model_output(self) -> None:
        self.assertFalse(
            contains_model_output(
                {
                    "run_id": "run-1",
                    "payload": {"run_type": "chat", "source": "agent_load_test"},
                }
            )
        )

    def test_first_model_request_latency_uses_result_timing(self) -> None:
        started_at = datetime.fromisoformat("2026-09-05T10:00:00+00:00")
        self.assertEqual(
            first_model_request_latency_ms(
                started_at,
                {"timing": {"first_model_request_at": "2026-09-05T10:00:01.250000Z"}},
            ),
            1250.0,
        )

    def test_first_model_request_latency_is_unknown_without_callback_timestamp(
        self,
    ) -> None:
        started_at = datetime.fromisoformat("2026-09-05T10:00:00+00:00")
        self.assertIsNone(first_model_request_latency_ms(started_at, {"timing": {}}))

    def test_run_creation_timing_is_distinct_from_client_submit(self) -> None:
        started_at = datetime.fromisoformat("2026-09-05T10:00:00+00:00")
        timing = {
            "created_at": "2026-09-05T10:00:00.250000Z",
            "first_model_request_at": "2026-09-05T10:00:01.250000Z",
            "first_model_request_latency_ms": 1000.0,
        }
        result = TaskResult(level=10, task_index=1, request_id="timing-test")
        record_run_timing(result, started_at, {"timing": timing})
        self.assertEqual(result.first_model_request_ms, 1250.0)
        self.assertEqual(result.created_to_first_model_request_ms, 1000.0)
        self.assertEqual(result.run_timing, timing)
        missing = TaskResult(level=10, task_index=2, request_id="missing-timing")
        record_run_timing(missing, started_at, {"timing": {}})
        summary = summarize([result, missing])[0]
        self.assertEqual(summary["created_to_first_model_request_p95_ms"], 1000.0)
        self.assertEqual(summary["missing_model_request_timing"], 1)

    def test_sandbox_result_accepts_same_run_with_tool_evidence(self) -> None:
        success, error, output_chars = evaluate_result(
            scenario="sandbox",
            payload={
                "status": "completed",
                "request_id": "request-1",
                "agent_run_id": "run-1",
                "output": "LOAD_TEST_OK",
            },
            request_id="request-1",
            run_id="run-1",
            evidence=ToolEvidence(execute_started=True, execute_finished=True, output_marker_seen=True),
        )

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(output_chars, len("LOAD_TEST_OK"))

    def test_result_rejects_neighbor_run(self) -> None:
        success, error, _ = evaluate_result(
            scenario="sandbox",
            payload={
                "status": "completed",
                "request_id": "request-1",
                "agent_run_id": "run-neighbor",
                "output": "LOAD_TEST_OK",
            },
            request_id="request-1",
            run_id="run-1",
            evidence=ToolEvidence(execute_started=True, execute_finished=True, output_marker_seen=True),
        )

        self.assertFalse(success)
        self.assertIn("agent_run_id", error or "")

    def test_parse_concurrency_rejects_out_of_range_value(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_concurrency("1,501")

    def test_exited_container_memory_is_skipped(self) -> None:
        self.assertIsNone(_parse_memory_mb("--"))
        self.assertAlmostEqual(_parse_memory_mb("1 GiB") or 0, 1024)

    def test_resource_sampler_uses_distinct_sandbox_prefixes(self) -> None:
        commands = []

        def fake_run(command, *, allow_partial=False):
            del allow_partial
            commands.append(command)
            if command[1:3] == ["network", "ls"]:
                return "network-prefix-one\nother-network\n"
            return "container-id\tcontainer-prefix-one\n"

        sampler = LocalResourceSampler(
            "project-one",
            "container-prefix",
            "network-prefix",
        )
        with patch("test.performance.load._run_local_command", side_effect=fake_run):
            self.assertEqual(sampler._sandbox_containers(), ["container-id"])
            self.assertEqual(sampler._sandbox_network_count(), 1)

        self.assertEqual(commands[0][3], "name=container-prefix")
        self.assertEqual(commands[1][4], "name=network-prefix")

    def test_parser_reads_distinct_sandbox_prefix_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SANDBOX_DOCKER_SANDBOX_PREFIX": "container-prefix",
                "SANDBOX_DOCKER_NETWORK_PREFIX": "network-prefix",
            },
        ):
            args = build_parser().parse_args(["load"])

        self.assertEqual(args.sandbox_container_prefix, "container-prefix")
        self.assertEqual(args.sandbox_network_prefix, "network-prefix")

    def test_summarize_uses_nearest_rank_and_counts_failures(self) -> None:
        summary = summarize(
            [
                TaskResult(level=2, task_index=1, request_id="a", success=True, total_ms=100),
                TaskResult(level=2, task_index=2, request_id="b", success=False, total_ms=300),
            ]
        )[0]

        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["success_rate"], 0.5)
        self.assertEqual(summary["total_p50_ms"], 100)
        self.assertEqual(summary["total_p95_ms"], 300)
        self.assertIn("request_queue_p95_ms", summary)
        self.assertIn("first_run_event_p95_ms", summary)
        self.assertIn("first_token_p95_ms", summary)

    def test_write_results_omits_credentials_and_full_output(self) -> None:
        result = TaskResult(
            level=1,
            task_index=1,
            request_id="request-1",
            run_id="run-1",
            success=True,
            output_chars=1234,
        )
        with tempfile.TemporaryDirectory() as tempdir:
            json_path, csv_path, resources_path = write_results(
                output_dir=Path(tempdir),
                config={"scenario": "chat", "base_url": "http://test"},
                results=[result],
                summaries=summarize([result]),
            )
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            csv_text = csv_path.read_text(encoding="utf-8")
            resources_text = resources_path.read_text(encoding="utf-8")

        self.assertNotIn("output", payload["requests"][0])
        self.assertNotIn("authorization", json.dumps(payload).lower())
        self.assertNotIn("authorization", csv_text.lower())
        self.assertIn("host_available_memory_mb", resources_text)
