"""将 LangGraph v3 Model 生命周期投影为 PostgreSQL AIMessage。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from yuxi.repositories.model_message_audit_repository import ModelMessageAuditRepository
from yuxi.storage.postgres.manager import pg_manager


@dataclass(slots=True)
class _ModelOperation:
    """保存单次 Model 生命周期的进程内聚合状态。"""

    operation_id: str
    monotonic_started_at: float | None
    content_parts: list[str] = field(default_factory=list)
    content_blocks: list[dict[str, Any]] = field(default_factory=list)


class ModelMessageAuditCollector:
    """按 message lifecycle 串行提交 Model 审计短事务。"""

    def __init__(self, *, run_id: str, request_id: str, thread_id: str, worker_id: str):
        self.run_id = run_id
        self.request_id = request_id
        self.thread_id = thread_id
        self.worker_id = worker_id
        self._operations: dict[tuple[str, str], _ModelOperation] = {}

    async def consume(self, message: Any, metadata: dict[str, Any] | None) -> None:
        """消费一条 raw messages ProtocolEvent；非生命周期消息保持无副作用。"""
        if not isinstance(message, dict) or not isinstance(message.get("event"), str):
            return

        metadata = dict(metadata or {})
        stream_event = metadata.get("stream_event") if isinstance(metadata.get("stream_event"), dict) else {}
        namespace = [str(item) for item in stream_event.get("namespace") or metadata.get("namespace") or []]
        key = self._operation_key(metadata, namespace)
        event_name = message["event"]

        if event_name == "message-start":
            await self._start(message, metadata, stream_event, key, namespace)
            return

        operation = self._operations.get(key)
        if operation is None:
            return

        if event_name == "content-block-delta":
            text = self._text_delta(message)
            if text:
                operation.content_parts.append(text)
            return

        if event_name == "content-block-finish":
            content = message.get("content")
            if isinstance(content, dict):
                operation.content_blocks.append(dict(content))
            return

        if event_name == "message-finish":
            await self._finish(message, stream_event, key, operation, namespace)

    async def _start(
        self,
        message: dict[str, Any],
        metadata: dict[str, Any],
        stream_event: dict[str, Any],
        key: tuple[str, str],
        namespace: list[str],
    ) -> None:
        """持久化 Model start 并初始化进程内增量聚合。"""
        operation_id = str(message.get("id") or metadata.get("run_id") or "").strip()
        if not operation_id:
            raise ValueError("message-start 缺少稳定 Model operation id")
        current_operation = self._operations.get(key)
        if current_operation is not None and current_operation.operation_id != operation_id:
            raise ValueError("同一 Model lifecycle 不能更换 operation id")
        sequence = self._sequence(stream_event)
        started_at = self._wall_clock(stream_event)
        monotonic_started_at = monotonic()

        async with pg_manager.get_async_session_context() as db:
            _message, created = await ModelMessageAuditRepository(db).start(
                run_id=self.run_id,
                request_id=self.request_id,
                thread_id=self.thread_id,
                worker_id=self.worker_id,
                operation_id=operation_id,
                sequence=sequence,
                started_at=started_at,
                metadata={
                    "id": str(message.get("id") or operation_id),
                    "audit_kind": "model",
                    "namespace": namespace,
                    "model_run_id": metadata.get("run_id"),
                    "start_metadata": dict(message.get("metadata") or {}),
                },
            )

        if current_operation is None:
            self._operations[key] = _ModelOperation(
                operation_id=operation_id,
                monotonic_started_at=monotonic_started_at if created else None,
            )

    async def _finish(
        self,
        message: dict[str, Any],
        stream_event: dict[str, Any],
        key: tuple[str, str],
        operation: _ModelOperation,
        namespace: list[str],
    ) -> None:
        """用聚合内容和原始 usage 关闭同一 Model lifecycle。"""
        finished_at = self._wall_clock(stream_event)
        duration_ms = (
            max(0, round((monotonic() - operation.monotonic_started_at) * 1000))
            if operation.monotonic_started_at is not None
            else None
        )
        usage = message.get("usage") if isinstance(message.get("usage"), dict) else None
        tool_calls = [block for block in operation.content_blocks if block.get("type") == "tool_call"]

        async with pg_manager.get_async_session_context() as db:
            await ModelMessageAuditRepository(db).finish(
                run_id=self.run_id,
                request_id=self.request_id,
                thread_id=self.thread_id,
                worker_id=self.worker_id,
                operation_id=operation.operation_id,
                content="".join(operation.content_parts),
                finished_at=finished_at,
                duration_ms=duration_ms,
                usage=usage,
                metadata={
                    "namespace": namespace,
                    "content": operation.content_blocks,
                    "tool_calls": tool_calls,
                    "finished_sequence": self._sequence(stream_event),
                    "finish_metadata": dict(message.get("metadata") or {}),
                },
            )
        self._operations.pop(key, None)

    @staticmethod
    def _operation_key(metadata: dict[str, Any], namespace: list[str]) -> tuple[str, str]:
        return str(metadata.get("run_id") or metadata.get("langgraph_node") or ""), "/".join(namespace)

    @staticmethod
    def _text_delta(message: dict[str, Any]) -> str:
        delta = message.get("delta") if isinstance(message.get("delta"), dict) else {}
        if delta.get("type") == "text-delta" and isinstance(delta.get("text"), str):
            return delta["text"]
        fields = delta.get("fields") if isinstance(delta.get("fields"), dict) else {}
        if fields.get("type") == "text-delta" and isinstance(fields.get("text"), str):
            return fields["text"]
        return ""

    @staticmethod
    def _sequence(stream_event: dict[str, Any]) -> int:
        sequence = stream_event.get("seq")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError("Model lifecycle 缺少有效 ProtocolEvent seq")
        return sequence

    @staticmethod
    def _wall_clock(stream_event: dict[str, Any]) -> datetime:
        timestamp = stream_event.get("timestamp")
        if not isinstance(timestamp, int | float) or isinstance(timestamp, bool):
            raise ValueError("Model lifecycle 缺少有效 params.timestamp")
        return datetime.fromtimestamp(timestamp / 1000, UTC).replace(tzinfo=None)
