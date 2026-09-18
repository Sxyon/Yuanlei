"""编码执行器适配器：统一 headless 命令与事件归一化。"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from typing import Any, Protocol

VALID_CODING_EXECUTORS = ("opencode", "codex")


@dataclass(frozen=True)
class CodingTurnRequest:
    """一次 headless turn 的输入。"""

    prompt: str
    model: str | None = None
    session_ref: str | None = None
    plan_only: bool = False
    workdir: str | None = None
    env: dict[str, str] | None = None
    prelude: str | None = None


@dataclass(frozen=True)
class NormalizedEvent:
    """跨执行器归一化事件；kind 为稳定契约。"""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CodingTurnResult:
    """一次 turn 的最终结果摘要。"""

    output_text: str
    session_ref: str | None
    usage: dict[str, Any] | None
    error: str | None


class CodingExecutorAdapter(Protocol):
    executor: str

    def build_command(self, request: CodingTurnRequest) -> str: ...

    def parse_events(self, output: str) -> list[NormalizedEvent]: ...


def _with_workdir(command: str, workdir: str | None) -> str:
    if not workdir:
        return command
    return f"cd {shlex.quote(workdir)} && {command}"


def _apply_turn_wrapper(command: str, request: CodingTurnRequest) -> str:
    """按需前置 prelude 与 env 赋值；env 只承载路径等非密值。"""
    wrapped = command
    if request.env:
        assignments = " ".join(
            f"{key}={shlex.quote(str(value))}"
            for key, value in sorted(request.env.items())
        )
        if assignments:
            wrapped = f"env {assignments} {wrapped}"
    if request.prelude:
        wrapped = f"{request.prelude} && {wrapped}"
    return wrapped


def _iter_json_lines(output: str):
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield payload


def extract_turn_result(events: list[NormalizedEvent]) -> CodingTurnResult:
    """从归一化事件派生最终文本、会话引用、用量与错误。"""
    texts: list[str] = []
    session_ref: str | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None
    for event in events:
        if event.kind == "output_delta":
            texts.append(str(event.payload.get("text") or ""))
        elif event.kind == "session_ref":
            session_ref = str(event.payload.get("session_ref") or "") or session_ref
        elif event.kind == "usage":
            usage = dict(event.payload)
        elif event.kind == "error":
            error = str(event.payload.get("message") or "coding executor failed")
    return CodingTurnResult(
        output_text="".join(texts).strip(),
        session_ref=session_ref,
        usage=usage,
        error=error,
    )


class OpenCodeAdapter:
    """opencode 1.4.x：`opencode run --format json`。"""

    executor = "opencode"

    def build_command(self, request: CodingTurnRequest) -> str:
        parts = ["opencode", "run", "--format", "json"]
        if request.plan_only:
            parts += ["--agent", "plan"]
        if request.model:
            parts += ["-m", request.model]
        if request.session_ref:
            parts += ["-s", request.session_ref]
        parts.append(request.prompt)
        command = " ".join(shlex.quote(part) for part in parts)
        return _with_workdir(_apply_turn_wrapper(command, request), request.workdir)

    def parse_events(self, output: str) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        for payload in _iter_json_lines(output):
            event_type = str(payload.get("type") or "")
            part = payload.get("part") or {}
            session_id = payload.get("sessionID") or part.get("sessionID")
            if event_type == "step_start":
                if session_id:
                    events.append(NormalizedEvent("session_ref", {"session_ref": session_id}))
            elif event_type == "text":
                events.append(NormalizedEvent("output_delta", {"text": part.get("text") or ""}))
            elif event_type == "tool":
                events.append(
                    NormalizedEvent(
                        "tool_call",
                        {
                            "tool": part.get("tool") or "tool",
                            "state": part.get("state") or {},
                        },
                    )
                )
            elif event_type == "step_finish":
                tokens = part.get("tokens") or {}
                events.append(
                    NormalizedEvent(
                        "usage",
                        {
                            "tokens": tokens,
                            "cost": part.get("cost"),
                            "reason": part.get("reason"),
                        },
                    )
                )
            elif event_type == "error":
                message = ((payload.get("error") or {}).get("data") or {}).get("message")
                events.append(NormalizedEvent("error", {"message": message or "opencode error"}))
            else:
                events.append(
                    NormalizedEvent(
                        "warning",
                        {"message": f"unknown opencode event type: {event_type or '<empty>'}"},
                    )
                )
        return events


class CodexAdapter:
    """codex-cli 0.139：`codex exec --json` / `codex exec resume <id> --json`。"""

    executor = "codex"

    def build_command(self, request: CodingTurnRequest) -> str:
        if request.session_ref:
            parts = ["codex", "exec", "resume", request.session_ref]
        else:
            parts = ["codex", "exec"]
        parts.append("--json")
        parts.append("--skip-git-repo-check")
        parts += ["-s", "read-only" if request.plan_only else "workspace-write"]
        if request.model:
            parts += ["-m", request.model]
        parts.append(request.prompt)
        command = " ".join(shlex.quote(part) for part in parts)
        return _with_workdir(_apply_turn_wrapper(command, request), request.workdir)

    def parse_events(self, output: str) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        for payload in _iter_json_lines(output):
            event_type = str(payload.get("type") or "")
            if event_type == "thread.started":
                thread_id = payload.get("thread_id")
                if thread_id:
                    events.append(NormalizedEvent("session_ref", {"session_ref": thread_id}))
            elif event_type == "turn.started":
                continue
            elif event_type == "item.completed":
                item = payload.get("item") or {}
                item_type = str(item.get("type") or "")
                if item_type == "agent_message":
                    events.append(NormalizedEvent("output_delta", {"text": item.get("text") or ""}))
                elif item_type == "command_execution":
                    events.append(
                        NormalizedEvent(
                            "tool_call",
                            {
                                "tool": "shell",
                                "command": item.get("command"),
                                "status": item.get("status"),
                            },
                        )
                    )
                elif item_type in {"file_change", "patch_apply"}:
                    events.append(NormalizedEvent("file_change", dict(item)))
                else:
                    events.append(
                        NormalizedEvent(
                            "warning",
                            {"message": f"unknown codex item type: {item_type or '<empty>'}"},
                        )
                    )
            elif event_type == "turn.completed":
                events.append(NormalizedEvent("usage", {"usage": payload.get("usage") or {}}))
            elif event_type in {"error", "turn.failed"}:
                message = payload.get("message")
                if not message:
                    message = (payload.get("error") or {}).get("message")
                events.append(NormalizedEvent("error", {"message": message or "codex error"}))
            else:
                events.append(
                    NormalizedEvent(
                        "warning",
                        {"message": f"unknown codex event type: {event_type or '<empty>'}"},
                    )
                )
        return events


_ADAPTERS: dict[str, CodingExecutorAdapter] = {
    "opencode": OpenCodeAdapter(),
    "codex": CodexAdapter(),
}


def get_coding_adapter(executor: str) -> CodingExecutorAdapter:
    """按执行器名取适配器；未知执行器显式失败。"""
    normalized = str(executor or "").strip().lower()
    adapter = _ADAPTERS.get(normalized)
    if adapter is None:
        raise ValueError(f"unsupported coding executor: {executor!r}")
    return adapter
