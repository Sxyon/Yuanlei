"""将 LangGraph v3 Tool 生命周期投影为 PostgreSQL ToolMessage。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from yuxi.repositories.tool_message_audit_repository import ToolMessageAuditRepository
from yuxi.storage.postgres.manager import pg_manager


class ToolMessageAuditCollector:
    """按 tools lifecycle 串行提交 ToolMessage 审计短事务。"""

    def __init__(self, *, run_id: str, request_id: str, thread_id: str, worker_id: str):
        self.run_id = run_id
        self.request_id = request_id
        self.thread_id = thread_id
        self.worker_id = worker_id
        self._operations: dict[str, float | None] = {}

    async def consume(self, event: Any) -> None:
        """消费一条根 tools ProtocolEvent；非生命周期事件保持无副作用。"""
        if not isinstance(event, dict) or event.get("method") != "tools":
            return
        data = event.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("event"), str):
            return

        event_name = data["event"]
        if event_name == "tool-started":
            await self._start(event, data)
        elif event_name == "tool-finished":
            await self._finish(event, data)
        elif event_name == "tool-error":
            await self._error(event, data)

    async def _start(self, event: dict[str, Any], data: dict[str, Any]) -> None:
        tool_call_id = self._tool_call_id(data)
        tool_name = str(data.get("tool_name") or "").strip()
        tool_input = data.get("input")
        if tool_input is None:
            tool_input = {}
        if not isinstance(tool_input, dict):
            raise ValueError("tool-started input 必须是对象")

        sequence = self._sequence(event)
        started_at = self._wall_clock(event)
        monotonic_started_at = monotonic()
        namespace = self._namespace(event)
        async with pg_manager.get_async_session_context() as db:
            _message, created = await ToolMessageAuditRepository(db).start(
                run_id=self.run_id,
                request_id=self.request_id,
                thread_id=self.thread_id,
                worker_id=self.worker_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_input=dict(tool_input),
                sequence=sequence,
                started_at=started_at,
                metadata={"namespace": namespace},
            )

        if created:
            self._operations[tool_call_id] = monotonic_started_at
        else:
            self._operations.setdefault(tool_call_id, None)

    async def _finish(self, event: dict[str, Any], data: dict[str, Any]) -> None:
        tool_call_id = self._tool_call_id(data)
        output = data.get("output")
        content = _tool_output_content(output)
        failed = isinstance(output, dict) and output.get("status") == "error"
        error_message = content if failed else None
        await self._close(
            event=event,
            tool_call_id=tool_call_id,
            output=output,
            content=content,
            error_message=error_message,
        )

    async def _error(self, event: dict[str, Any], data: dict[str, Any]) -> None:
        tool_call_id = self._tool_call_id(data)
        error_message = str(data.get("message") or "Tool 执行失败")
        await self._close(
            event=event,
            tool_call_id=tool_call_id,
            output=None,
            content="",
            error_message=error_message,
            wait_for_run_terminal=True,
        )

    async def _close(
        self,
        *,
        event: dict[str, Any],
        tool_call_id: str,
        output: Any,
        content: str,
        error_message: str | None,
        wait_for_run_terminal: bool = False,
    ) -> None:
        """将进程内计时与 terminal 事实一次提交给 Repository。"""
        monotonic_started_at = self._operations.get(tool_call_id)
        duration_ms = (
            max(0, round((monotonic() - monotonic_started_at) * 1000)) if monotonic_started_at is not None else None
        )
        kwargs = {
            "run_id": self.run_id,
            "request_id": self.request_id,
            "thread_id": self.thread_id,
            "worker_id": self.worker_id,
            "tool_call_id": tool_call_id,
            "output": output,
            "content": content,
            "finished_at": self._wall_clock(event),
            "duration_ms": duration_ms,
            "finished_sequence": self._sequence(event),
        }
        async with pg_manager.get_async_session_context() as db:
            repository = ToolMessageAuditRepository(db)
            if wait_for_run_terminal:
                await repository.observe_error(
                    run_id=self.run_id,
                    request_id=self.request_id,
                    thread_id=self.thread_id,
                    worker_id=self.worker_id,
                    tool_call_id=tool_call_id,
                    error_message=error_message or "Tool 执行失败",
                    finished_at=kwargs["finished_at"],
                    duration_ms=duration_ms,
                    finished_sequence=kwargs["finished_sequence"],
                )
            elif error_message is None:
                await repository.complete(**kwargs)
            else:
                await repository.fail(error_message=error_message, **kwargs)
        self._operations.pop(tool_call_id, None)

    @staticmethod
    def _tool_call_id(data: dict[str, Any]) -> str:
        tool_call_id = str(data.get("tool_call_id") or "").strip()
        if not tool_call_id:
            raise ValueError("Tool lifecycle 缺少稳定 tool_call_id")
        return tool_call_id

    @staticmethod
    def _sequence(event: dict[str, Any]) -> int:
        sequence = event.get("seq")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError("Tool lifecycle 缺少有效 ProtocolEvent seq")
        return sequence

    @staticmethod
    def _wall_clock(event: dict[str, Any]) -> datetime:
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, int | float) or isinstance(timestamp, bool):
            raise ValueError("Tool lifecycle 缺少有效 params.timestamp")
        return datetime.fromtimestamp(timestamp / 1000, UTC).replace(tzinfo=None)

    @staticmethod
    def _namespace(event: dict[str, Any]) -> list[str]:
        namespace = event.get("namespace")
        return [str(item) for item in namespace] if isinstance(namespace, list) else []


def _tool_output_content(output: Any) -> str:
    """将 ToolMessage output 规整为兼容展示文本，同时保留原始 output metadata。"""
    value = output.get("content") if isinstance(output, dict) else output
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)
