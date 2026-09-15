"""在隔离 Compose 槽位测量不同用户的 API 接入到模型发送时延。"""

import argparse
import asyncio
import json
import math
import os
import secrets
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .load import (
    TERMINAL_STATUSES,
    AgentLoadClient,
    authenticate,
    parse_concurrency,
    resolve_agent_slug,
)

ROOT = Path(__file__).resolve().parents[3]


def command(args):
    """执行实验所需命令，失败时不回显可能含凭据的日志。"""
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args[:4])}")
    return result.stdout


def compose_args():
    """显式使用实验覆盖文件，槽位由调用方环境指定。"""
    return [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        str(Path(__file__).with_name("compose.yml")),
    ]


def read_probe_events(since):
    """只提取结构化探针，不保存应用日志或模型正文。"""
    raw = command([*compose_args(), "logs", "--no-color", "--since", since, "api", "worker"])
    events = []
    for line in raw.splitlines():
        if "MATRIX_TIMING " in line:
            event = json.loads(line.split("MATRIX_TIMING ", 1)[1])
            event["container"] = line.split("|", 1)[0].strip()
            events.append(event)
    return events


def read_runs(run_ids):
    """回读精确 Run 的时点、执行次数和输出绑定，不读取正文。"""
    ids = ",".join("'" + str(uuid.UUID(value)) + "'" for value in run_ids)
    if not ids:
        return []
    sql = f"""SELECT coalesce(json_agg(t),'[]'::json) FROM (
        SELECT r.id, r.request_id, r.uid, r.status, r.created_at, r.started_at,
        q.created_at AS request_created_at, r.prepared_at, r.first_output_at, r.finished_at,
        r.first_model_request_at, r.output_message_id,
        (SELECT count(*) FROM agent_run_attempts a WHERE a.run_id=r.id) AS attempts,
        EXISTS(SELECT 1 FROM messages m WHERE m.id=r.output_message_id AND m.run_id=r.id) AS bound_output
        FROM agent_runs r JOIN agent_run_requests q ON q.request_id=r.request_id
        WHERE r.id IN ({ids})) t"""
    return json.loads(
        command(
            [
                *compose_args(),
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "postgres",
                "-d",
                "yuxi",
                "-Atc",
                sql,
            ]
        )
    )


def percentile(values, ratio):
    """使用 nearest-rank；缺失值不会伪装为零。"""
    values = sorted(value for value in values if value is not None)
    return round(values[max(0, math.ceil(len(values) * ratio) - 1)], 2) if values else None


def channel_rounds(concurrency, override=None):
    """正式矩阵按请求预算分配轮数；小实验可显式覆盖，不另发预热。"""
    if override is not None:
        if override < 1:
            raise ValueError("每 Thread 轮数必须为正数")
        return override
    return {1: 100, 10: 10, 20: 5, 50: 5, 100: 5}[concurrency]


def stages_complete(requests, events):
    """API 与 Worker 都结束分块输出后，才能声称阶段明细完整。"""
    expected = {("request_id", row["request_id"]) for row in requests}
    expected.update(("run_id", row["run_id"]) for row in requests if row["run_id"])
    completed = {
        (key, event[key])
        for event in events
        if event["event"] == "stages_done"
        for key in ("request_id", "run_id")
        if key in event
    }
    return expected.issubset(completed)


def join_timings(requests, events, runs):
    """按精确请求和 Run 合并服务端时点，保留失败及缺失。"""
    arrivals = {e["request_id"]: e for e in events if e["event"] == "api_received"}
    sends = {e["run_id"]: e for e in events if e["event"] == "model_send"}
    stored = {row["id"]: row for row in runs}
    details = {}
    for event in events:
        if event["event"] == "stage_spans":
            details.setdefault(event.get("run_id") or event.get("request_id"), []).extend(event["spans"])
    for request in requests:
        row = stored.get(request.get("run_id"))
        if row and (row["request_id"] != request["request_id"] or row["uid"] != request["uid"]):
            raise ValueError("Run 与请求或用户串绑")
        arrival, sent = (
            arrivals.get(request["request_id"]),
            sends.get(request.get("run_id")),
        )
        request.update(
            db=row,
            api_received_ns=arrival["time_ns"] if arrival else None,
            model_send_ns=sent["time_ns"] if sent else None,
            worker=sent["container"] if sent else None,
            spans=sent["spans"] if sent else [],
        )
        if details:
            request["api_spans"] = details.get(request["request_id"], [])
            request["spans"] = details.get(request.get("run_id"), [])
        request["api_to_model_ms"] = (sent["time_ns"] - arrival["time_ns"]) / 1e6 if sent and arrival else None
        if row:
            points = {
                "api": arrival["time_ns"] / 1e6 if arrival else None,
                "model": sent["time_ns"] / 1e6 if sent else None,
            }
            for key in (
                "request_created",
                "created",
                "started",
                "prepared",
                "first_output",
                "finished",
            ):
                raw = row.get(key + "_at")
                points[key] = datetime.fromisoformat(raw).replace(tzinfo=UTC).timestamp() * 1000 if raw else None
            for metric, start, end in (
                ("api_to_request_created_ms", "api", "request_created"),
                ("api_to_created_ms", "api", "created"),
                ("created_to_started_ms", "created", "started"),
                ("started_to_model_ms", "started", "model"),
                ("started_to_prepared_ms", "started", "prepared"),
                ("prepared_to_model_ms", "prepared", "model"),
                ("model_to_first_output_ms", "model", "first_output"),
                ("api_to_first_output_ms", "api", "first_output"),
                ("first_output_to_finished_ms", "first_output", "finished"),
                ("api_to_finished_ms", "api", "finished"),
            ):
                request[metric] = (
                    points[end] - points[start] if points[start] is not None and points[end] is not None else None
                )
            if request["api_to_model_ms"] is not None and request["api_to_model_ms"] < 0:
                raise ValueError("服务端时间顺序错误")
    return requests


async def cancel_failed_request(load_client, row):
    """确认精确请求已终止；取消失败留在样本中，不连带取消其他通道。"""
    try:
        async with asyncio.timeout(10):
            if not row["run_id"]:
                response = await load_client.client.post(
                    f"/api/agent/requests/{row['request_id']}/cancel",
                    headers=load_client.headers,
                )
                if response.status_code == 409:
                    detail = response.json().get("detail", {})
                    if detail.get("code") != "request_already_dispatched":
                        response.raise_for_status()
                    row["run_id"] = str(uuid.UUID(detail["run_id"]))
                else:
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("request_id") != row["request_id"] or payload.get("status") not in TERMINAL_STATUSES:
                        raise ValueError("未确认精确 Request 终态")
                    row["cancel_confirmed"] = True
                    return
            response = await load_client.client.post(
                f"/api/agent/runs/{row['run_id']}/cancel", headers=load_client.headers
            )
            response.raise_for_status()
            while True:
                result = await load_client.get_run_result(row["run_id"])
                if result.get("request_id") != row["request_id"] or result.get("agent_run_id") != row["run_id"]:
                    raise ValueError("取消结果与精确 Request/Run 串绑")
                if result.get("status") in TERMINAL_STATUSES:
                    row["cancel_confirmed"] = True
                    return
                await asyncio.sleep(0.1)
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError, TimeoutError) as exc:
        row["cancel_error"] = type(exc).__name__


async def run_request(load_client, slug, thread_id, request_id, uid, *, row=None):
    """发送一次 say hi 并回读同 Run 结果；不限制输出。"""
    if row is None:
        row = {}
    row.update(
        request_id=request_id,
        uid=uid,
        thread_id=thread_id,
        run_id=None,
        success=False,
        client_started_ns=time.time_ns(),
    )
    submitted = time.perf_counter()
    load_client.headers = {**load_client.headers, "X-Load-Test-Id": request_id}
    try:
        async with asyncio.timeout(load_client.timeout_seconds):
            payload, row["client_submit_response_ms"] = await load_client.submit_run(
                agent_slug=slug,
                thread_id=thread_id,
                request_id=request_id,
                prompt="say hi",
            )
            row["run_id"] = payload.get("run_id") or await load_client.wait_for_run_id(
                request_id, payload["request_events_url"]
            )
            (
                _,
                _,
                row["client_first_event_ms"],
                row["client_first_token_ms"],
                _,
            ) = await load_client.consume_run_events(row["run_id"], submitted)
            result = await load_client.get_run_result(row["run_id"])
            row["status"] = result.get("status")
            row["success"] = (
                result.get("request_id") == request_id
                and result.get("agent_run_id") == row["run_id"]
                and result.get("status") == "completed"
                and bool(result.get("output"))
            )
    except (httpx.HTTPError, RuntimeError, ValueError, TimeoutError) as exc:
        row["error"] = type(exc).__name__
        await cancel_failed_request(load_client, row)
    except BaseException as exc:
        row["error"] = type(exc).__name__
        await cancel_failed_request(load_client, row)
        raise
    finally:
        row["client_completed_ns"] = time.time_ns()
        row["client_total_ms"] = (time.perf_counter() - submitted) * 1000
    return row


async def run_channel(prepared, rounds, channel_index, samples=None):
    """同一用户和 Thread 连续补位，无跨通道轮次屏障；失败停止本通道。"""
    load, slug, thread_id, first_request_id, uid = prepared
    rows = []
    for turn in range(1, rounds + 1):
        request_id = first_request_id if turn == 1 else f"matrix-{uuid.uuid4().hex}"
        row = {"channel": channel_index, "turn": turn, "success": False}
        rows.append(row)
        if samples is not None:
            samples.append(row)
        row.update(await run_request(load, slug, thread_id, request_id, uid, row=row))
        if not row["success"]:
            break
    return rows


def summarize_timings(rows):
    """分开统计服务端阶段和客户端体验，并保留每项实际样本数。"""
    metrics = (
        "api_to_request_created_ms",
        "api_to_created_ms",
        "created_to_started_ms",
        "started_to_prepared_ms",
        "prepared_to_model_ms",
        "api_to_model_ms",
        "model_to_first_output_ms",
        "api_to_first_output_ms",
        "first_output_to_finished_ms",
        "api_to_finished_ms",
        "client_submit_response_ms",
        "client_first_event_ms",
        "client_first_token_ms",
        "client_total_ms",
    )
    summary = {}
    for metric in metrics:
        values = [row.get(metric) for row in rows]
        summary[metric] = {
            "n": sum(value is not None for value in values),
            "p50": percentile(values, 0.5),
            "p95": percentile(values, 0.95),
        }
    return summary


def verified_completed(row):
    """成功由精确 Run 的持久终态、唯一 attempt 与绑定输出共同证明。"""
    stored = row.get("db") or {}
    return (
        row["success"]
        and stored.get("status") == "completed"
        and stored.get("attempts") == 1
        and stored.get("bound_output") is True
    )


async def record_group(report, group, path, since):
    """先保存付费样本，再收集阶段；探针失败仍保留原始证据并显式停止。"""
    report.setdefault("groups", []).append(group)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    try:
        requests = group["requests"]
        group["events"] = await asyncio.to_thread(read_probe_events, since)
        if os.getenv("MATRIX_FINE_TIMING") == "1":
            for _ in range(50):
                if stages_complete(requests, group["events"]):
                    break
                await asyncio.sleep(0.1)
                group["events"] = await asyncio.to_thread(read_probe_events, since)
            group["stages_complete"] = stages_complete(requests, group["events"])
        runs = await asyncio.to_thread(read_runs, [r["run_id"] for r in requests if r["run_id"]])
        join_timings(requests, group["events"], runs)
        timings = summarize_timings(requests)
        group.update(
            verified_completed=sum(verified_completed(row) for row in requests),
            p95_ms=timings["api_to_model_ms"]["p95"],
            p50_ms=timings["api_to_model_ms"]["p50"],
            missing=len(requests) - timings["api_to_model_ms"]["n"],
            timings=timings,
            by_turn={
                turn: summarize_timings([r for r in requests if r["turn"] == turn])
                for turn in range(1, group["rounds_per_thread"] + 1)
            },
        )
        if group.get("stages_complete") is False:
            raise RuntimeError("阶段探针未完整输出；已保存样本，停止后续实验")
        if group["missing"] or group["verified_completed"] != len(requests):
            raise RuntimeError("样本时点或持久结果不完整；已保存样本，停止后续实验")
    except Exception as exc:
        group["observation_error"] = type(exc).__name__
        raise
    finally:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


async def main(args):
    """准备测试身份、运行矩阵并清理精确测试资源。"""
    project = os.getenv("COMPOSE_PROJECT_NAME", "")
    if project != "yuxi-alpha" or os.getenv("YUXI_STATE_DIR") != "../.yuxi/slots/alpha":
        raise RuntimeError("本实验只允许显式指定 Alpha project 与状态目录")
    rounds_by_level = {level: channel_rounds(level, args.rounds_per_thread) for level in args.concurrency}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if (args.output_dir / "matrix.json").exists():
        raise FileExistsError("输出目录已包含实验结果，请使用新目录以保留付费样本")
    report = {
        "project": project,
        "prompt": "say hi",
        "groups": [],
        "rounds_by_concurrency": rounds_by_level,
        "load_pattern": "closed_loop",
        "probe_mode": "fine" if os.getenv("MATRIX_FINE_TIMING") == "1" else "semantic",
    }
    users, threads = [], []
    retained_threads, retained_users = set(), set()
    async with httpx.AsyncClient(
        base_url=args.base_url,
        timeout=200,
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=100),
    ) as client:
        admin = await authenticate(client)
        slug = await resolve_agent_slug(client, admin, args.agent_slug)
        report["agent_slug"] = slug
        try:
            session = uuid.uuid4().hex[:8]
            for index in range(max(args.concurrency)):
                response = await client.post(
                    "/api/auth/users",
                    headers=admin,
                    json={
                        "username": f"matrix{session}{index}",
                        "password": secrets.token_urlsafe(24),
                        "role": "user",
                    },
                )
                response.raise_for_status()
                user = response.json()
                users.append({"id": user["id"], "uid": user["uid"]})
                token = await client.post(f"/api/auth/impersonate/{user['id']}", headers=admin)
                token.raise_for_status()
                users[-1]["headers"] = {"Authorization": "Bearer " + token.json()["access_token"]}
            print(f"已准备 {len(users)} 个不同用户", flush=True)
            for workers in args.workers:
                since = datetime.now(UTC).isoformat()
                await asyncio.to_thread(
                    command,
                    [
                        *compose_args(),
                        "up",
                        "-d",
                        "--no-deps",
                        "--scale",
                        f"worker={workers}",
                        "--force-recreate",
                        "worker",
                    ],
                )
                deadline = time.monotonic() + 180
                while True:
                    events = await asyncio.to_thread(read_probe_events, since)
                    ready = {e["container"] for e in events if e["event"] == "worker_ready"}
                    if len(ready) == workers:
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError("worker 启动超时")
                    await asyncio.sleep(2)
                for level in args.concurrency:
                    rounds = rounds_by_level[level]
                    selected = users[:level]
                    prepared = []
                    for index, user in enumerate(selected):
                        load = AgentLoadClient(client, user["headers"], 180)
                        request_id = f"matrix-{session}-{workers}-{level}-{uuid.uuid4().hex[:12]}"
                        thread_id = await load.create_thread(slug, request_id)
                        threads.append((load, thread_id))
                        prepared.append((load, slug, thread_id, request_id, user["uid"]))
                    group_start = datetime.now(UTC).isoformat()
                    started = time.perf_counter()
                    requests = []
                    group_error = None
                    # 请求发出前保守保留资源，只有精确终态确认后才允许删除。
                    retained_threads.update(item[2] for item in prepared)
                    retained_users.update(item[4] for item in prepared)
                    try:
                        async with asyncio.TaskGroup() as tasks:
                            for index, item in enumerate(prepared):
                                tasks.create_task(run_channel(item, rounds, index, requests))
                    except BaseException as exc:
                        group_error = exc
                    duration = time.perf_counter() - started
                    uncertain = [
                        r
                        for r in requests
                        if not r["success"]
                        and not r.get("cancel_confirmed")
                        and r.get("status") not in TERMINAL_STATUSES
                    ]
                    observed_threads = {r.get("thread_id") for r in requests}
                    uncertain_threads = {r.get("thread_id") for r in uncertain}
                    for _, _, thread_id, _, uid in prepared:
                        if thread_id in observed_threads and thread_id not in uncertain_threads:
                            retained_threads.discard(thread_id)
                            retained_users.discard(uid)
                    group = {
                        "workers": workers,
                        "concurrency": level,
                        "warmup": False,
                        "rounds_per_thread": rounds,
                        "requests": requests,
                        "failed": sum(not r["success"] for r in requests),
                        "unconfirmed_terminal": len(uncertain),
                        "planned_requests": level * rounds,
                        "actual_requests": len(requests),
                        "duration_seconds": duration,
                        "successful_rps": sum(r["success"] for r in requests) / duration,
                        "expected_workers": sorted(ready),
                    }
                    if group_error is not None:
                        group["observation_error"] = type(group_error).__name__
                        report["groups"].append(group)
                        (args.output_dir / "matrix.json").write_text(
                            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
                        )
                        raise group_error
                    await record_group(report, group, args.output_dir / "matrix.json", group_start)
                    print(
                        json.dumps(
                            {k: v for k, v in group.items() if k not in {"requests", "events", "timings", "by_turn"}},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    if uncertain:
                        raise RuntimeError("有请求未确认终态，保留其测试资源并停止后续实验")
                    # 各批结果回读后清理会话，避免下一批仍有请求在运行。
                    for load, thread_id in threads:
                        await load.delete_thread(thread_id)
                    threads.clear()
        finally:
            for load, thread_id in threads:
                if thread_id not in retained_threads:
                    await load.delete_thread(thread_id)
            for user in users:
                if user["uid"] in retained_users:
                    continue
                response = await client.delete(f"/api/auth/users/{user['id']}", headers=admin)
                response.raise_for_status()
            print(
                f"已删除本轮 {len(users) - len(retained_users)} 个测试用户，"
                f"保留 {len(retained_users)} 个未确认终态用户",
                flush=True,
            )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """注册不同用户闭环矩阵的采样参数。"""
    parser.add_argument("--base-url", default="http://localhost:25050")
    parser.add_argument("--agent-slug")
    parser.add_argument("--workers", type=parse_concurrency, default=[1, 4, 8])
    parser.add_argument("--concurrency", type=parse_concurrency, default=[1, 10, 20, 50, 100])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--rounds-per-thread",
        type=int,
        help="覆盖每通道轮数供小实验使用；默认按正式矩阵预算运行，无额外预热",
    )
