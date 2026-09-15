"""通过真实 Yuxi HTTP、SSE、worker 与模型链路执行轻量 Agent 压测。"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

FINAL_MARKER = "LOAD_TEST_OK"
TOOL_MARKER = "LOAD_TEST_TOOL_OK"
CHAT_MIN_OUTPUT_CHARS = 500
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


class LoadTestError(RuntimeError):
    """表示一次压测任务无法继续或协议结果不满足约束。"""


@dataclass(frozen=True)
class SseEvent:
    """保存一个解析后的 SSE 事件。"""

    name: str
    data: dict[str, Any]
    event_id: str | None = None


@dataclass
class ToolEvidence:
    """记录沙盒 execute 工具在事件流中的完成证据。"""

    execute_started: bool = False
    execute_finished: bool = False
    output_marker_seen: bool = False


@dataclass
class TaskResult:
    """保存单个虚拟用户的协议标识、耗时和最终判定。"""

    level: int
    task_index: int
    request_id: str
    thread_id: str | None = None
    run_id: str | None = None
    status: str = "client_failed"
    success: bool = False
    thread_create_ms: float | None = None
    submit_ms: float | None = None
    request_queue_ms: float | None = None
    preparation_ms: float | None = None
    first_model_request_ms: float | None = None
    created_to_first_model_request_ms: float | None = None
    run_timing: dict[str, Any] | None = None
    first_run_event_ms: float | None = None
    first_token_ms: float | None = None
    run_sse_ms: float | None = None
    total_ms: float | None = None
    output_chars: int = 0
    event_counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ResourceSample:
    """保存一个并发档位内的本机资源快照。"""

    level: int
    elapsed_ms: float
    captured_at: str
    api_memory_mb: float | None = None
    worker_memory_mb: float | None = None
    provisioner_memory_mb: float | None = None
    sandbox_memory_mb: float | None = None
    total_memory_mb: float | None = None
    api_cpu_percent: float | None = None
    worker_cpu_percent: float | None = None
    provisioner_cpu_percent: float | None = None
    sandbox_cpu_percent: float | None = None
    total_cpu_percent: float | None = None
    redis_clients: int | None = None
    redis_pubsub_clients: int | None = None
    postgres_connections: int | None = None
    postgres_active_connections: int | None = None
    sandbox_containers: int | None = None
    sandbox_networks: int | None = None
    host_available_memory_mb: float | None = None
    host_load1: float | None = None
    error: str | None = None


def parse_concurrency(value: str) -> list[int]:
    """解析逗号分隔的并发阶梯，并拒绝危险或含糊的输入。"""

    try:
        levels = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("并发阶梯必须是逗号分隔的整数") from exc
    if not levels or any(level < 1 or level > 500 for level in levels):
        raise argparse.ArgumentTypeError("每个并发值必须在 1 到 500 之间")
    return levels


def parse_task_seconds(value: str) -> int:
    """解析受沙盒执行超时约束的任务时长。"""

    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("任务时长必须是整数") from exc
    if seconds < 1 or seconds > 120:
        raise argparse.ArgumentTypeError("任务时长必须在 1 到 120 秒之间")
    return seconds


async def iter_sse(lines: AsyncIterator[str]) -> AsyncIterator[SseEvent]:
    """把 HTTP 行流解析为 SSE 事件；heartbeat 不产生事件。"""

    event_name = "message"
    event_id: str | None = None
    data_lines: list[str] = []

    async for line in lines:
        if line == "":
            if data_lines:
                yield _build_sse_event(event_name, event_id, data_lines)
            event_name = "message"
            event_id = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field_name, separator, raw_value = line.partition(":")
        if not separator:
            continue
        value = raw_value.removeprefix(" ")
        if field_name == "event":
            event_name = value or "message"
        elif field_name == "id":
            event_id = value or None
        elif field_name == "data":
            data_lines.append(value)

    if data_lines:
        yield _build_sse_event(event_name, event_id, data_lines)


def _build_sse_event(name: str, event_id: str | None, data_lines: Sequence[str]) -> SseEvent:
    """解析单个 SSE JSON 数据块。"""

    raw_data = "\n".join(data_lines)
    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError as exc:
        raise LoadTestError(f"SSE {name} 事件不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise LoadTestError(f"SSE {name} 事件 data 必须是对象")
    return SseEvent(name=name, data=payload, event_id=event_id)


def observe_tool_evidence(value: object, evidence: ToolEvidence) -> None:
    """递归读取精简 Run 事件中的 execute 生命周期证据。"""

    if isinstance(value, dict):
        if value.get("tool_name") == "execute":
            event_name = value.get("event")
            evidence.execute_started |= event_name == "tool-started"
            evidence.execute_finished |= event_name == "tool-finished"
            if event_name == "tool-finished" and TOOL_MARKER in str(value.get("output") or ""):
                evidence.output_marker_seen = True
        if value.get("type") == "tool" and TOOL_MARKER in str(value.get("content") or ""):
            # verbose=false 会把完成事件投影为 ToolMessage；唯一标记证明受控命令已经返回。
            evidence.execute_finished = True
            evidence.output_marker_seen = True
        for child in value.values():
            observe_tool_evidence(child, evidence)
    elif isinstance(value, list):
        for child in value:
            observe_tool_evidence(child, evidence)


def contains_model_output(value: object) -> bool:
    """识别模型产生的首个文本或工具调用增量。"""

    if isinstance(value, dict):
        event_type = value.get("type")
        if event_type == "message_delta" and any(
            isinstance(value.get(key), str) and bool(value[key])
            for key in ("content", "reasoning_content", "additional_reasoning_content")
        ):
            return True
        if event_type in {"tool_call", "tool_call_delta"} and any(
            value.get(key) is not None and value.get(key) != "" and value.get(key) != {}
            for key in ("name", "args", "args_delta")
        ):
            return True
        return any(contains_model_output(child) for child in value.values())
    if isinstance(value, list):
        return any(contains_model_output(child) for child in value)
    return False


_MEMORY_UNITS = {
    "B": 1,
    "kB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "KiB": 1024,
    "MiB": 1024**2,
    "GiB": 1024**3,
}


def _parse_memory_mb(value: str) -> float | None:
    """把 Docker stats 的内存值转换为 MiB。"""

    if value.strip() == "--":
        return None
    match = re.fullmatch(r"\s*([0-9.]+)\s*([A-Za-z]+)\s*", value)
    if not match or match.group(2) not in _MEMORY_UNITS:
        raise LoadTestError(f"无法解析 Docker 内存值：{value}")
    return float(match.group(1)) * _MEMORY_UNITS[match.group(2)] / 1024**2


def _run_local_command(command: Sequence[str], *, allow_partial: bool = False) -> str:
    """执行只读本机探针并返回标准输出。"""

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if completed.returncode != 0 and not (allow_partial and completed.stdout.strip()):
        detail = completed.stderr.strip().replace("\n", " ")[:300]
        raise LoadTestError(f"资源探针失败：{' '.join(command[:3])}：{detail}")
    return completed.stdout


class LocalResourceSampler:
    """按 Compose project 采样本机容器和服务资源。"""

    def __init__(
        self,
        compose_project: str,
        sandbox_container_prefix: str,
        sandbox_network_prefix: str,
    ):
        self.compose_project = compose_project
        self.sandbox_container_prefix = sandbox_container_prefix
        self.sandbox_network_prefix = sandbox_network_prefix

    def collect(self, level: int, level_started: float) -> ResourceSample:
        """采集一次不会修改运行状态的资源快照。"""

        sample = ResourceSample(
            level=level,
            elapsed_ms=round((time.perf_counter() - level_started) * 1000, 2),
            captured_at=datetime.now(UTC).isoformat(),
        )
        try:
            compose_containers = self._compose_containers()
            sandbox_containers = [
                container_id for container_id in self._sandbox_containers() if container_id not in compose_containers
            ]
            service_by_id = {container_id: service for container_id, service in compose_containers.items()}
            service_by_id.update({container_id: "sandbox" for container_id in sandbox_containers})
            memory, cpu = self._container_stats(service_by_id)

            sample.api_memory_mb = memory.get("api", 0.0)
            sample.worker_memory_mb = memory.get("worker", 0.0)
            sample.provisioner_memory_mb = memory.get("sandbox-provisioner", 0.0)
            sample.sandbox_memory_mb = memory.get("sandbox", 0.0)
            sample.total_memory_mb = round(sum(memory.values()), 2)
            sample.api_cpu_percent = cpu.get("api", 0.0)
            sample.worker_cpu_percent = cpu.get("worker", 0.0)
            sample.provisioner_cpu_percent = cpu.get("sandbox-provisioner", 0.0)
            sample.sandbox_cpu_percent = cpu.get("sandbox", 0.0)
            sample.total_cpu_percent = round(sum(cpu.values()), 2)
            sample.sandbox_containers = len(sandbox_containers)
            sample.sandbox_networks = self._sandbox_network_count()
            sample.redis_clients, sample.redis_pubsub_clients = self._redis_client_metrics(compose_containers)
            (
                sample.postgres_connections,
                sample.postgres_active_connections,
            ) = self._postgres_connection_metrics(compose_containers)
            sample.host_available_memory_mb = self._host_available_memory_mb()
            sample.host_load1 = float(Path("/proc/loadavg").read_text().split()[0])
        except (LoadTestError, OSError, ValueError, subprocess.SubprocessError) as exc:
            sample.error = _safe_error(exc)
        return sample

    def _compose_containers(self) -> dict[str, str]:
        output = _run_local_command(
            [
                "docker",
                "ps",
                "--filter",
                f"label=com.docker.compose.project={self.compose_project}",
                "--format",
                '{{.ID}}\t{{.Label "com.docker.compose.service"}}',
            ]
        )
        return {
            container_id: service
            for line in output.splitlines()
            if line.strip()
            for container_id, service in [line.split("\t", 1)]
        }

    def _sandbox_containers(self) -> list[str]:
        output = _run_local_command(
            [
                "docker",
                "ps",
                "--filter",
                f"name={self.sandbox_container_prefix}",
                "--format",
                "{{.ID}}\t{{.Names}}",
            ]
        )
        return [
            container_id
            for line in output.splitlines()
            if line.strip()
            for container_id, name in [line.split("\t", 1)]
            if name.startswith(self.sandbox_container_prefix)
        ]

    def _container_stats(self, service_by_id: dict[str, str]) -> tuple[dict[str, float], dict[str, float]]:
        memory: dict[str, float] = {}
        cpu: dict[str, float] = {}
        if not service_by_id:
            return memory, cpu
        output = _run_local_command(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            allow_partial=True,
        )
        for line in output.splitlines():
            row = json.loads(line)
            container_id = str(row.get("ID") or "")
            service = next(
                (
                    value
                    for key, value in service_by_id.items()
                    if key.startswith(container_id) or container_id.startswith(key)
                ),
                None,
            )
            if service is None and str(row.get("Name") or "").startswith(self.sandbox_container_prefix):
                service = "sandbox"
            if service is None:
                continue
            used_memory = str(row.get("MemUsage") or "").split("/", 1)[0]
            parsed_memory = _parse_memory_mb(used_memory)
            if parsed_memory is None:
                continue
            memory[service] = memory.get(service, 0.0) + parsed_memory
            cpu_value = float(str(row.get("CPUPerc") or "0").strip().removesuffix("%") or 0)
            cpu[service] = cpu.get(service, 0.0) + cpu_value
        return (
            {key: round(value, 2) for key, value in memory.items()},
            {key: round(value, 2) for key, value in cpu.items()},
        )

    def _redis_client_metrics(self, containers: dict[str, str]) -> tuple[int, int]:
        container_id = next(key for key, value in containers.items() if value == "redis")
        output = _run_local_command(["docker", "exec", container_id, "redis-cli", "--raw", "INFO", "clients"])
        metrics = {
            key: int(value)
            for line in output.splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
            if key in {"connected_clients", "pubsub_clients"}
        }
        return metrics["connected_clients"], metrics.get("pubsub_clients", 0)

    def _postgres_connection_metrics(self, containers: dict[str, str]) -> tuple[int, int]:
        container_id = next(key for key, value in containers.items() if value == "postgres")
        output = _run_local_command(
            [
                "docker",
                "exec",
                container_id,
                "sh",
                "-c",
                (
                    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc '
                    '"SELECT count(*), count(*) FILTER '
                    "(WHERE state = 'active') FROM pg_stat_activity\""
                ),
            ]
        )
        total, active = output.strip().split("|", 1)
        return int(total), int(active)

    def _sandbox_network_count(self) -> int:
        output = _run_local_command(
            [
                "docker",
                "network",
                "ls",
                "--filter",
                f"name={self.sandbox_network_prefix}",
                "--format",
                "{{.Name}}",
            ]
        )
        return sum(name.startswith(self.sandbox_network_prefix) for name in output.splitlines())

    @staticmethod
    def _host_available_memory_mb() -> float:
        line = next(line for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))
        return round(float(line.split()[1]) / 1024, 2)


async def sample_resources(
    *,
    sampler: LocalResourceSampler,
    level: int,
    level_started: float,
    interval_seconds: float,
    stop_event: asyncio.Event,
    samples: list[ResourceSample],
) -> None:
    """在并发档位执行期间周期采样，并在结束时保留最后快照。"""

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            samples.append(await asyncio.to_thread(sampler.collect, level, level_started))
    samples.append(await asyncio.to_thread(sampler.collect, level, level_started))


def evaluate_result(
    *,
    scenario: str,
    payload: dict[str, Any],
    request_id: str,
    run_id: str,
    evidence: ToolEvidence,
) -> tuple[bool, str | None, int]:
    """按同一 Request/Run 因果关系与场景标记判定最终结果。"""

    status = str(payload.get("status") or "")
    output = payload.get("output")
    output_text = output if isinstance(output, str) else ""
    checks = [
        (payload.get("request_id") == request_id, "结果 request_id 与提交请求不一致"),
        (payload.get("agent_run_id") == run_id, "结果 agent_run_id 与 SSE Run 不一致"),
        (status == "completed", f"Run 终态不是 completed：{status or 'missing'}"),
        (FINAL_MARKER in output_text, "最终输出缺少 LOAD_TEST_OK"),
    ]
    if scenario == "chat":
        checks.append(
            (
                len(output_text) >= CHAT_MIN_OUTPUT_CHARS,
                f"最终输出少于 {CHAT_MIN_OUTPUT_CHARS} 字符",
            )
        )
    else:
        checks.extend(
            [
                (evidence.execute_started, "事件流中没有 execute tool-started"),
                (evidence.execute_finished, "事件流中没有 execute tool-finished"),
                (evidence.output_marker_seen, "execute 输出缺少 LOAD_TEST_TOOL_OK"),
            ]
        )
    errors = [message for passed, message in checks if not passed]
    return not errors, "; ".join(errors) if errors else None, len(output_text)


def build_prompt(scenario: str, task_seconds: int, task_id: str) -> str:
    """构造不会访问知识库的长文本或受控沙盒任务。"""

    if scenario == "chat":
        return (
            f"这是一次 Agent 长连接压测，任务编号 {task_id}。"
            "请分析高并发 Agent 系统从请求接入、排队、模型调用到结果返回的主要瓶颈，"
            "给出不少于 800 个中文字符的连贯说明。不要调用任何工具或知识库。"
            f"最后单独一行输出 {FINAL_MARKER}。"
        )
    command = f"sleep {task_seconds} && printf '{TOOL_MARKER}\\n'"
    return (
        f"这是一次 Agent 沙盒长连接压测，任务编号 {task_id}。"
        f"必须调用 execute 工具且只执行一次这个命令：{command}。"
        f"等待工具执行完成并确认输出包含 {TOOL_MARKER} 后，仅回复 {FINAL_MARKER}。"
    )


def first_model_request_latency_ms(
    submit_started_at: datetime,
    result_payload: dict[str, Any],
) -> float | None:
    """计算客户端提交起点到首次进入 ChatModel 请求边界的时延。"""

    timing = result_payload.get("timing")
    if not isinstance(timing, dict):
        return None
    raw_started_at = timing.get("first_model_request_at")
    if not isinstance(raw_started_at, str) or not raw_started_at.strip():
        return None
    try:
        model_request_started_at = datetime.fromisoformat(raw_started_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if model_request_started_at.tzinfo is None:
        model_request_started_at = model_request_started_at.replace(tzinfo=UTC)
    return round((model_request_started_at - submit_started_at).total_seconds() * 1000, 2)


def record_run_timing(result: TaskResult, submit_started_at: datetime, payload: dict[str, Any]) -> None:
    """保留服务端原始计时，并分开记录 Run 创建与客户端提交口径。"""
    timing = payload.get("timing")
    if not isinstance(timing, dict):
        return
    result.run_timing = dict(timing)
    result.created_to_first_model_request_ms = timing.get("first_model_request_latency_ms")
    result.first_model_request_ms = first_model_request_latency_ms(submit_started_at, payload)


class AgentLoadClient:
    """封装压测所需的最小 Yuxi HTTP 与 SSE 协议。"""

    def __init__(self, client: httpx.AsyncClient, headers: dict[str, str], timeout_seconds: float):
        self.client = client
        self.headers = headers
        self.timeout_seconds = timeout_seconds

    async def create_thread(self, agent_slug: str, request_id: str) -> str:
        """创建一个独立压测 Thread。"""

        response = await self.client.post(
            "/api/chat/thread",
            json={
                "request_id": f"thread-{request_id}"[:64],
                "title": f"Load test {request_id[-12:]}",
                "agent_id": agent_slug,
                "metadata": {"source": "agent_load_test"},
            },
            headers=self.headers,
        )
        _raise_for_status(response, "创建 Thread")
        thread_id = str(response.json().get("id") or "")
        if not thread_id:
            raise LoadTestError("创建 Thread 响应缺少 id")
        return thread_id

    async def submit_run(
        self,
        *,
        agent_slug: str,
        thread_id: str,
        request_id: str,
        prompt: str,
    ) -> tuple[dict[str, Any], float]:
        """提交普通 Chat Request 并返回协议响应与请求耗时。"""

        started = time.perf_counter()
        response = await self.client.post(
            "/api/agent/runs",
            json={
                "query": prompt,
                "agent_slug": agent_slug,
                "thread_id": thread_id,
                "meta": {"request_id": request_id, "source": "agent_load_test"},
                "tool_approval_mode": "always_trust",
                "queue_policy": "enqueue",
            },
            headers=self.headers,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        _raise_for_status(response, "提交 Agent Run")
        payload = response.json()
        if payload.get("request_id") != request_id:
            raise LoadTestError("提交响应 request_id 与请求不一致")
        return payload, elapsed_ms

    async def wait_for_run_id(self, request_id: str, events_url: str) -> str:
        """消费 Request SSE，直到排队请求创建其自身 Run。"""

        async with self.client.stream("GET", events_url, headers=self.headers) as response:
            await _raise_for_stream_status(response, "读取 Request SSE")
            async for event in iter_sse(response.aiter_lines()):
                if event.data.get("request_id") not in {None, request_id}:
                    raise LoadTestError("Request SSE 包含其他 request_id")
                if event.name == "run_created":
                    run_id = str(event.data.get("run_id") or "")
                    if not run_id:
                        raise LoadTestError("run_created 事件缺少 run_id")
                    return run_id
                if event.name in {"error", "cancelled", "superseded"}:
                    raise LoadTestError(f"Request SSE 以 {event.name} 结束")
        raise LoadTestError("Request SSE 结束但没有 run_created")

    async def consume_run_events(
        self,
        run_id: str,
        submit_started: float,
    ) -> tuple[dict[str, int], ToolEvidence, float | None, float | None, float]:
        """消费 Run SSE 到 end，并返回准备、首输出与工具证据。"""

        counts: dict[str, int] = {}
        evidence = ToolEvidence()
        first_event_ms: float | None = None
        first_token_ms: float | None = None
        stream_started = time.perf_counter()
        async with self.client.stream(
            "GET",
            f"/api/agent/runs/{run_id}/events?verbose=false",
            headers=self.headers,
        ) as response:
            await _raise_for_stream_status(response, "读取 Run SSE")
            async for event in iter_sse(response.aiter_lines()):
                if first_event_ms is None:
                    first_event_ms = (time.perf_counter() - submit_started) * 1000
                if event.data.get("run_id") not in {None, run_id}:
                    raise LoadTestError("Run SSE 包含其他 run_id")
                counts[event.name] = counts.get(event.name, 0) + 1
                observe_tool_evidence(event.data, evidence)
                if first_token_ms is None and contains_model_output(event.data):
                    first_token_ms = (time.perf_counter() - submit_started) * 1000
                if event.name == "error":
                    raise LoadTestError("Run SSE 收到 error 事件")
                if event.name == "end":
                    return (
                        counts,
                        evidence,
                        first_event_ms,
                        first_token_ms,
                        (time.perf_counter() - stream_started) * 1000,
                    )
        raise LoadTestError("Run SSE 结束但没有 end 事件")

    async def get_run_result(self, run_id: str) -> dict[str, Any]:
        """从同一 Run 的结果接口回读最终业务事实。"""

        response = await self.client.get(f"/api/agent/runs/{run_id}/result", headers=self.headers)
        _raise_for_status(response, "读取 Run 结果")
        payload = response.json()
        if not isinstance(payload, dict):
            raise LoadTestError("Run 结果必须是对象")
        return payload

    async def cancel_request(self, request_id: str) -> None:
        """尽力取消尚未派发的精确 Request。"""

        await self.client.post(f"/api/agent/requests/{request_id}/cancel", headers=self.headers)

    async def cancel_run(self, run_id: str) -> None:
        """尽力取消尚未终结的精确 Run。"""

        await self.client.post(f"/api/agent/runs/{run_id}/cancel", headers=self.headers)

    async def delete_thread(self, thread_id: str) -> None:
        """删除本任务创建的精确 Thread。"""

        response = await self.client.delete(f"/api/chat/thread/{thread_id}", headers=self.headers)
        if response.status_code not in {200, 404}:
            _raise_for_status(response, "删除 Thread")


async def run_one(
    *,
    load_client: AgentLoadClient,
    agent_slug: str,
    scenario: str,
    task_seconds: int,
    level: int,
    task_index: int,
    session_id: str,
    keep_threads: bool,
) -> TaskResult:
    """执行一个虚拟用户的完整 Thread → Request → Run → Result 链路。"""

    request_id = f"load-{session_id}-{level}-{task_index}-{uuid.uuid4().hex[:8]}"
    result = TaskResult(level=level, task_index=task_index, request_id=request_id)
    task_started = time.perf_counter()
    submit_started: float | None = None
    submit_started_at: datetime | None = None
    terminal = False
    try:
        async with asyncio.timeout(load_client.timeout_seconds):
            result.thread_id = await load_client.create_thread(agent_slug, request_id)
            result.thread_create_ms = (time.perf_counter() - task_started) * 1000
            submit_started = time.perf_counter()
            submit_started_at = datetime.now(UTC)
            payload, result.submit_ms = await load_client.submit_run(
                agent_slug=agent_slug,
                thread_id=result.thread_id,
                request_id=request_id,
                prompt=build_prompt(scenario, task_seconds, request_id),
            )
            result.run_id = str(payload.get("run_id") or "") or None
            if result.run_id:
                result.request_queue_ms = 0.0
            else:
                events_url = str(payload.get("request_events_url") or "")
                if not events_url:
                    raise LoadTestError("排队响应同时缺少 run_id 与 request_events_url")
                queue_started = time.perf_counter()
                result.run_id = await load_client.wait_for_run_id(request_id, events_url)
                result.request_queue_ms = (time.perf_counter() - queue_started) * 1000

            (
                result.event_counts,
                evidence,
                result.first_run_event_ms,
                result.first_token_ms,
                result.run_sse_ms,
            ) = await load_client.consume_run_events(result.run_id, submit_started)
            result.preparation_ms = result.first_run_event_ms
            final_payload = await load_client.get_run_result(result.run_id)
            result.status = str(final_payload.get("status") or "missing")
            if submit_started_at is not None:
                record_run_timing(result, submit_started_at, final_payload)
            terminal = result.status in TERMINAL_STATUSES
            result.success, result.error, result.output_chars = evaluate_result(
                scenario=scenario,
                payload=final_payload,
                request_id=request_id,
                run_id=result.run_id,
                evidence=evidence,
            )
    except TimeoutError:
        result.error = f"任务超过 {load_client.timeout_seconds:g} 秒"
    except (httpx.HTTPError, LoadTestError, ValueError) as exc:
        result.error = _safe_error(exc)
    finally:
        if submit_started is not None:
            result.total_ms = (time.perf_counter() - submit_started) * 1000
        if not terminal:
            try:
                if result.run_id:
                    await load_client.cancel_run(result.run_id)
                else:
                    await load_client.cancel_request(request_id)
            except httpx.HTTPError:
                pass
        if result.thread_id and not keep_threads:
            try:
                await load_client.delete_thread(result.thread_id)
            except (httpx.HTTPError, LoadTestError) as exc:
                cleanup_error = f"清理 Thread 失败：{_safe_error(exc)}"
                result.error = f"{result.error}; {cleanup_error}" if result.error else cleanup_error
                result.success = False
    return result


def summarize(
    results: Sequence[TaskResult],
    resource_samples: Sequence[ResourceSample] = (),
) -> list[dict[str, Any]]:
    """按并发阶梯汇总成功率和关键延迟分位数。"""

    summaries: list[dict[str, Any]] = []
    for level in dict.fromkeys(item.level for item in results):
        items = [item for item in results if item.level == level]
        successful = [item for item in items if item.success]
        summary = {
            "concurrency": level,
            "requests": len(items),
            "succeeded": len(successful),
            "failed": len(items) - len(successful),
            "success_rate": round(len(successful) / len(items), 4) if items else 0.0,
            "submit_p95_ms": _percentile([item.submit_ms for item in items], 0.95),
            "request_queue_p95_ms": _percentile([item.request_queue_ms for item in items], 0.95),
            "first_run_event_p95_ms": _percentile([item.first_run_event_ms for item in items], 0.95),
            "preparation_p50_ms": _percentile([item.preparation_ms for item in items], 0.50),
            "preparation_p95_ms": _percentile([item.preparation_ms for item in items], 0.95),
            "first_model_request_p50_ms": _percentile([item.first_model_request_ms for item in items], 0.50),
            "first_model_request_p95_ms": _percentile([item.first_model_request_ms for item in items], 0.95),
            "created_to_first_model_request_p50_ms": _percentile(
                [item.created_to_first_model_request_ms for item in items], 0.50
            ),
            "created_to_first_model_request_p95_ms": _percentile(
                [item.created_to_first_model_request_ms for item in items], 0.95
            ),
            "missing_model_request_timing": sum(item.created_to_first_model_request_ms is None for item in items),
            "first_token_p50_ms": _percentile([item.first_token_ms for item in items], 0.50),
            "first_token_p95_ms": _percentile([item.first_token_ms for item in items], 0.95),
            "total_p50_ms": _percentile([item.total_ms for item in items], 0.50),
            "total_p95_ms": _percentile([item.total_ms for item in items], 0.95),
            "total_max_ms": _percentile([item.total_ms for item in items], 1.0),
        }
        level_samples = [sample for sample in resource_samples if sample.level == level]
        if level_samples:
            summary.update(_summarize_resources(level_samples))
        summaries.append(summary)
    return summaries


def _summarize_resources(samples: Sequence[ResourceSample]) -> dict[str, Any]:
    """汇总一个并发档位的资源基线、峰值和采样完整性。"""

    valid_samples = [sample for sample in samples if sample.error is None]
    summary: dict[str, Any] = {
        "resource_samples": len(samples),
        "resource_sample_errors": len(samples) - len(valid_samples),
    }
    if not valid_samples:
        return summary

    peak_fields = (
        "api_memory_mb",
        "worker_memory_mb",
        "provisioner_memory_mb",
        "sandbox_memory_mb",
        "total_memory_mb",
        "api_cpu_percent",
        "worker_cpu_percent",
        "provisioner_cpu_percent",
        "sandbox_cpu_percent",
        "total_cpu_percent",
        "redis_clients",
        "redis_pubsub_clients",
        "postgres_connections",
        "postgres_active_connections",
        "sandbox_containers",
        "sandbox_networks",
        "host_load1",
    )
    for field_name in peak_fields:
        values = [value for sample in valid_samples if (value := getattr(sample, field_name)) is not None]
        summary[f"{field_name}_peak"] = round(max(values), 2) if values else None

    available_memory = [
        sample.host_available_memory_mb for sample in valid_samples if sample.host_available_memory_mb is not None
    ]
    summary["host_available_memory_mb_min"] = round(min(available_memory), 2) if available_memory else None
    baseline = valid_samples[0]
    for field_name in ("worker_memory_mb", "sandbox_memory_mb", "total_memory_mb"):
        peak = summary.get(f"{field_name}_peak")
        baseline_value = getattr(baseline, field_name)
        summary[f"{field_name}_baseline"] = baseline_value
        summary[f"{field_name}_increase"] = (
            round(peak - baseline_value, 2) if peak is not None and baseline_value is not None else None
        )
    return summary


def _percentile(values: Sequence[float | None], ratio: float) -> float | None:
    """使用 nearest-rank 计算小样本也可解释的分位数。"""

    ordered = sorted(value for value in values if value is not None)
    if not ordered:
        return None
    index = max(0, math.ceil(ratio * len(ordered)) - 1)
    return round(ordered[index], 2)


def write_results(
    *,
    output_dir: Path,
    config: dict[str, Any],
    results: Sequence[TaskResult],
    summaries: Sequence[dict[str, Any]],
    resource_samples: Sequence[ResourceSample] = (),
) -> tuple[Path, Path, Path]:
    """写出不含凭据与完整模型输出的结果和资源采样。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"agent-{config['scenario']}-{timestamp}"
    json_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}.csv"
    resources_path = output_dir / f"{stem}-resources.csv"
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "config": config,
        "summary": list(summaries),
        "requests": [asdict(item) for item in results],
        "resources": [asdict(sample) for sample in resource_samples],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows = [asdict(item) for item in results]
    for row in rows:
        row["event_counts"] = json.dumps(row["event_counts"], ensure_ascii=False, sort_keys=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]) if rows else list(TaskResult.__dataclass_fields__),
        )
        writer.writeheader()
        writer.writerows(rows)

    resource_rows = [asdict(sample) for sample in resource_samples]
    resource_fields = list(ResourceSample.__dataclass_fields__)
    with resources_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=resource_fields)
        writer.writeheader()
        writer.writerows(resource_rows)
    return json_path, csv_path, resources_path


def print_summary(summaries: Sequence[dict[str, Any]]) -> None:
    """向终端打印紧凑的阶梯汇总表。"""

    headers = (
        "并发",
        "请求",
        "成功",
        "失败",
        "成功率",
        "提交P95",
        "线程队列P95",
        "首Run事件P95",
        "提交→模型P95",
        "创建→模型P95",
        "计时缺失",
        "首Token P95",
        "总耗时P95",
    )
    print("  ".join(headers))
    for item in summaries:
        print(
            f"{item['concurrency']:>4}  {item['requests']:>4}  {item['succeeded']:>4}  "
            f"{item['failed']:>4}  {item['success_rate'] * 100:>6.1f}%  "
            f"{_format_ms(item['submit_p95_ms']):>9}  {_format_ms(item['request_queue_p95_ms']):>11}  "
            f"{_format_ms(item['first_run_event_p95_ms']):>12}  "
            f"{_format_ms(item['first_model_request_p95_ms']):>15}  "
            f"{_format_ms(item['created_to_first_model_request_p95_ms']):>15}  "
            f"{item['missing_model_request_timing']:>8}  "
            f"{_format_ms(item['first_token_p95_ms']):>11}  {_format_ms(item['total_p95_ms']):>11}"
        )


def _format_ms(value: float | None) -> str:
    """格式化毫秒指标。"""

    return "-" if value is None else f"{value:.0f}ms"


def _raise_for_status(response: httpx.Response, action: str) -> None:
    """把 HTTP 错误转换为不包含请求头的简短诊断。"""

    if response.is_success:
        return
    detail = response.text.replace("\n", " ")[:300]
    raise LoadTestError(f"{action}失败：HTTP {response.status_code} {detail}")


async def _raise_for_stream_status(response: httpx.Response, action: str) -> None:
    """读取失败流响应并转换为简短诊断。"""

    if response.is_success:
        return
    body = (await response.aread()).decode(errors="replace").replace("\n", " ")[:300]
    raise LoadTestError(f"{action}失败：HTTP {response.status_code} {body}")


def _safe_error(exc: BaseException) -> str:
    """限制结果文件中的异常文本长度。"""

    return str(exc).replace("\n", " ")[:500] or exc.__class__.__name__


async def authenticate(client: httpx.AsyncClient) -> dict[str, str]:
    """从环境变量取得 API Key，或通过真实登录接口换取访问令牌。"""

    api_key = os.getenv("YUXI_LOAD_API_KEY", "").strip()
    if api_key:
        return {"Authorization": f"Bearer {api_key}", "Accept": "text/event-stream"}

    username = (os.getenv("YUXI_LOAD_USERNAME") or os.getenv("TEST_USERNAME") or "").strip()
    password = os.getenv("YUXI_LOAD_PASSWORD") or os.getenv("TEST_PASSWORD") or ""
    if not username or not password:
        raise LoadTestError("请设置 YUXI_LOAD_API_KEY，或同时设置 YUXI_LOAD_USERNAME/YUXI_LOAD_PASSWORD")
    response = await client.post("/api/auth/token", data={"username": username, "password": password})
    _raise_for_status(response, "登录")
    token = str(response.json().get("access_token") or "")
    if not token:
        raise LoadTestError("登录响应缺少 access_token")
    return {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}


async def resolve_agent_slug(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    requested_slug: str | None,
) -> str:
    """验证指定 Agent，未指定时使用当前用户可见的默认 Agent。"""

    path = f"/api/agent/{requested_slug}" if requested_slug else "/api/agent/default"
    response = await client.get(path, headers=headers)
    _raise_for_status(response, "读取 Agent")
    agent = response.json().get("agent") or {}
    slug = str(agent.get("slug") or "")
    if not slug:
        raise LoadTestError("Agent 响应缺少 slug")
    return slug


async def async_main(args: argparse.Namespace) -> int:
    """校验环境、逐级执行压测并持久化结果。"""

    limits = httpx.Limits(
        max_connections=max(args.concurrency) + 10,
        max_keepalive_connections=max(args.concurrency) + 5,
    )
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"),
        timeout=httpx.Timeout(
            connect=10,
            read=args.timeout_seconds + 30,
            write=30,
            pool=30,
        ),
        limits=limits,
    ) as client:
        ready = await client.get("/api/system/ready")
        _raise_for_status(ready, "系统 readiness 检查")
        headers = await authenticate(client)
        agent_slug = await resolve_agent_slug(client, headers, args.agent_slug)
        load_client = AgentLoadClient(client, headers, args.timeout_seconds)
        session_id = uuid.uuid4().hex[:8]
        results: list[TaskResult] = []
        resource_samples: list[ResourceSample] = []
        resource_sampler = (
            LocalResourceSampler(
                args.compose_project,
                args.sandbox_container_prefix,
                args.sandbox_network_prefix,
            )
            if args.collect_local_resources
            else None
        )

        print(f"场景={args.scenario} Agent={agent_slug} 并发阶梯={args.concurrency}")
        for level in args.concurrency:
            print(f"开始并发 {level}：{level} 个独立 Thread")
            level_started = time.perf_counter()
            stop_sampling = asyncio.Event()
            if resource_sampler:
                resource_samples.append(await asyncio.to_thread(resource_sampler.collect, level, level_started))
            sampler_task = (
                asyncio.create_task(
                    sample_resources(
                        sampler=resource_sampler,
                        level=level,
                        level_started=level_started,
                        interval_seconds=args.resource_interval_seconds,
                        stop_event=stop_sampling,
                        samples=resource_samples,
                    )
                )
                if resource_sampler
                else None
            )
            try:
                level_results = await asyncio.gather(
                    *(
                        run_one(
                            load_client=load_client,
                            agent_slug=agent_slug,
                            scenario=args.scenario,
                            task_seconds=args.task_seconds,
                            level=level,
                            task_index=index,
                            session_id=session_id,
                            keep_threads=args.keep_threads,
                        )
                        for index in range(1, level + 1)
                    )
                )
            finally:
                if sampler_task:
                    stop_sampling.set()
                    await sampler_task
            results.extend(level_results)
            print_summary(summarize(level_results, resource_samples))

    summaries = summarize(results, resource_samples)
    config = {
        "base_url": args.base_url.rstrip("/"),
        "agent_slug": agent_slug,
        "scenario": args.scenario,
        "concurrency": args.concurrency,
        "task_seconds": args.task_seconds if args.scenario == "sandbox" else None,
        "timeout_seconds": args.timeout_seconds,
        "keep_threads": args.keep_threads,
        "collect_local_resources": args.collect_local_resources,
        "compose_project": args.compose_project if args.collect_local_resources else None,
        "sandbox_container_prefix": args.sandbox_container_prefix if args.collect_local_resources else None,
        "sandbox_network_prefix": args.sandbox_network_prefix if args.collect_local_resources else None,
        "resource_interval_seconds": args.resource_interval_seconds if args.collect_local_resources else None,
        "timing_metric": "created_to_first_model_request_ms",
        "timing_metric_definition": (
            "PostgreSQL AgentRun.created_at 到 LangChain on_chat_model_start 的差值；"
            "回调在供应商 HTTP 发送前触发，是发送前近似边界，不包含首 token 等待。"
        ),
        "client_timing_metric": "first_model_request_ms",
    }
    json_path, csv_path, resources_path = write_results(
        output_dir=args.output_dir,
        config=config,
        results=results,
        summaries=summaries,
        resource_samples=resource_samples,
    )
    print("最终汇总")
    print_summary(summaries)
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print(f"资源: {resources_path}")
    return 0 if all(item.success for item in results) else 1


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """注册容量压测参数。"""
    parser.add_argument(
        "--base-url",
        default=os.getenv("YUXI_LOAD_BASE_URL", "http://localhost:5050"),
        help="Yuxi API 根地址，默认 %(default)s",
    )
    parser.add_argument("--agent-slug", help="测试 Agent slug；省略时使用默认 Agent")
    parser.add_argument("--scenario", choices=("chat", "sandbox"), default="sandbox")
    parser.add_argument("--concurrency", type=parse_concurrency, default=parse_concurrency("1,5,10,20"))
    parser.add_argument("--task-seconds", type=parse_task_seconds, default=45)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/load-tests"))
    parser.add_argument("--keep-threads", action="store_true")
    parser.add_argument(
        "--collect-local-resources",
        action="store_true",
        help="按并发档位采样当前 Compose project 的本机资源",
    )
    parser.add_argument(
        "--compose-project",
        default=os.getenv("COMPOSE_PROJECT_NAME", "yuxi"),
        help="资源采样使用的 Compose project，默认 %(default)s",
    )
    parser.add_argument(
        "--sandbox-container-prefix",
        default=os.getenv("SANDBOX_DOCKER_SANDBOX_PREFIX") or f"{os.getenv('COMPOSE_PROJECT_NAME', 'yuxi')}-sandbox",
        help="动态 Sandbox 容器名称前缀",
    )
    parser.add_argument(
        "--sandbox-network-prefix",
        default=os.getenv("SANDBOX_DOCKER_NETWORK_PREFIX") or f"{os.getenv('COMPOSE_PROJECT_NAME', 'yuxi')}-sandbox",
        help="动态 Sandbox 网络名称前缀",
    )
    parser.add_argument("--resource-interval-seconds", type=float, default=2.0)


def main(args: argparse.Namespace) -> int:
    """运行命令行入口，并为启动阶段错误提供简短输出。"""

    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds 必须大于 0")
    if args.resource_interval_seconds <= 0:
        raise SystemExit("--resource-interval-seconds 必须大于 0")
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("压测已由用户中止", file=sys.stderr)
        return 130
    except (httpx.HTTPError, LoadTestError) as exc:
        print(f"压测未启动：{_safe_error(exc)}", file=sys.stderr)
        return 2
