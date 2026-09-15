"""ToolMessage 生命周期审计 Repository。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.agent_run_repository import AgentRunRepository
from yuxi.storage.postgres.models_business import (
    MODEL_AUDIT_MESSAGE_TYPE,
    TOOL_AUDIT_MESSAGE_TYPE,
    AgentRun,
    Message,
    ToolCall,
)


class ToolMessageAuditRepository:
    """以当前 Run lease 为边界持久化 ToolMessage 与 ToolCall 兼容投影。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.run_repo = AgentRunRepository(db_session)

    async def start(
        self,
        *,
        run_id: str,
        request_id: str,
        thread_id: str,
        worker_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        sequence: int,
        started_at: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Message, bool]:
        """幂等创建 running ToolMessage，并从该事实建立 ToolCall 兼容投影。"""
        operation_id = tool_call_id.strip()
        normalized_name = tool_name.strip()
        if not operation_id:
            raise ValueError("Tool tool_call_id 不能为空")
        if not normalized_name:
            raise ValueError("Tool tool_name 不能为空")
        if sequence < 0:
            raise ValueError("Tool sequence 不能为负数")

        run = await self._lock_run(
            run_id=run_id,
            request_id=request_id,
            thread_id=thread_id,
            worker_id=worker_id,
        )
        existing = await self._get(run_id, operation_id)
        if existing is not None:
            self._require_same_owner(existing, conversation_id=run.conversation_id, request_id=request_id)
            self._require_same_start(
                existing,
                tool_name=normalized_name,
                tool_input=tool_input,
                sequence=sequence,
            )
            return existing, False

        source_message = await self._find_source_model_message(run, operation_id)
        if source_message is None:
            raise ValueError("Tool start 无法关联声明该 tool_call_id 的 Model Message")
        audit_metadata = {
            **dict(metadata or {}),
            "audit_kind": "tool",
            "tool_call_id": operation_id,
            "tool_name": normalized_name,
            "input": dict(tool_input),
            "source_model_operation_id": source_message.operation_id,
        }
        message = Message(
            conversation_id=run.conversation_id,
            role="tool",
            content="",
            message_type=TOOL_AUDIT_MESSAGE_TYPE,
            extra_metadata=audit_metadata,
            run_id=run.id,
            request_id=request_id,
            delivery_status="complete",
            operation_id=operation_id,
            started_at=started_at,
            sequence=sequence,
            execution_status="running",
        )
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)

        tool_call = await self._get_tool_call_for_message(source_message.id, operation_id)
        if tool_call is None:
            tool_call = ToolCall(
                message_id=source_message.id,
                langgraph_tool_call_id=operation_id,
                tool_name=normalized_name,
                tool_input=dict(tool_input),
                status="pending",
            )
            self.db.add(tool_call)
        elif tool_call.status != "pending":
            raise ValueError("已结束 ToolCall 不能开始新的 ToolMessage lifecycle")
        else:
            tool_call.tool_name = normalized_name
            tool_call.tool_input = dict(tool_input)
        await self.db.flush()
        audit_metadata["compatibility_tool_call_id"] = tool_call.id
        message.extra_metadata = audit_metadata
        await self.db.flush()
        return message, True

    async def complete(
        self,
        *,
        run_id: str,
        request_id: str,
        thread_id: str,
        worker_id: str,
        tool_call_id: str,
        output: Any,
        content: str,
        finished_at: datetime,
        duration_ms: int | None,
        finished_sequence: int | None,
    ) -> Message:
        """完成同一 ToolMessage，并同步成功 ToolCall 投影。"""
        return await self._finish(
            run_id=run_id,
            request_id=request_id,
            thread_id=thread_id,
            worker_id=worker_id,
            tool_call_id=tool_call_id,
            execution_status="completed",
            tool_call_status="success",
            output=output,
            content=content,
            error_message=None,
            finished_at=finished_at,
            duration_ms=duration_ms,
            finished_sequence=finished_sequence,
        )

    async def fail(
        self,
        *,
        run_id: str,
        request_id: str,
        thread_id: str,
        worker_id: str,
        tool_call_id: str,
        error_message: str,
        output: Any,
        content: str,
        finished_at: datetime,
        duration_ms: int | None,
        finished_sequence: int | None,
    ) -> Message:
        """关闭失败 ToolMessage；终态 State 可补全 stream error 缺少的 ToolMessage 内容。"""
        return await self._finish(
            run_id=run_id,
            request_id=request_id,
            thread_id=thread_id,
            worker_id=worker_id,
            tool_call_id=tool_call_id,
            execution_status="failed",
            tool_call_status="error",
            output=output,
            content=content,
            error_message=error_message,
            finished_at=finished_at,
            duration_ms=duration_ms,
            finished_sequence=finished_sequence,
        )

    async def observe_error(
        self,
        *,
        run_id: str,
        request_id: str,
        thread_id: str,
        worker_id: str,
        tool_call_id: str,
        error_message: str,
        finished_at: datetime,
        duration_ms: int | None,
        finished_sequence: int,
    ) -> Message:
        """保存裸 tool-error，最终状态由 Run failed/interrupted 事务裁决。"""
        operation_id = tool_call_id.strip()
        if not operation_id:
            raise ValueError("Tool tool_call_id 不能为空")
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("Tool duration_ms 不能为负数")
        if finished_sequence < 0:
            raise ValueError("Tool finished_sequence 不能为负数")
        run = await self._lock_run(
            run_id=run_id,
            request_id=request_id,
            thread_id=thread_id,
            worker_id=worker_id,
        )
        message = await self._get(run_id, operation_id)
        if message is None:
            raise ValueError("Tool error 缺少对应的 start 事实")
        self._require_same_owner(message, conversation_id=run.conversation_id, request_id=request_id)
        if message.execution_status != "running":
            metadata = message.extra_metadata if isinstance(message.extra_metadata, dict) else {}
            if metadata.get("error_message") != error_message:
                raise ValueError("已关闭 Tool 审计事实不能被不同错误覆盖")
            return message

        metadata = dict(message.extra_metadata or {})
        metadata["error_message"] = error_message
        metadata["finished_sequence"] = finished_sequence
        metadata["awaiting_run_terminal"] = True
        message.extra_metadata = metadata
        message.finished_at = finished_at
        message.duration_ms = duration_ms
        await self.db.flush()
        await self.db.refresh(message)
        return message

    async def list_for_run(self, run_id: str) -> list[Message]:
        """按 ProtocolEvent sequence 返回 Run 的 ToolMessage。"""
        result = await self.db.execute(
            select(Message)
            .where(
                Message.run_id == run_id,
                Message.message_type == TOOL_AUDIT_MESSAGE_TYPE,
                Message.role == "tool",
            )
            .order_by(Message.sequence.asc(), Message.id.asc())
        )
        return list(result.scalars().all())

    async def _finish(
        self,
        *,
        run_id: str,
        request_id: str,
        thread_id: str,
        worker_id: str,
        tool_call_id: str,
        execution_status: Literal["completed", "failed"],
        tool_call_status: Literal["success", "error"],
        output: Any,
        content: str,
        error_message: str | None,
        finished_at: datetime,
        duration_ms: int | None,
        finished_sequence: int | None,
    ) -> Message:
        """原子关闭 Tool 审计及其兼容 ToolCall。"""
        operation_id = tool_call_id.strip()
        if not operation_id:
            raise ValueError("Tool tool_call_id 不能为空")
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("Tool duration_ms 不能为负数")
        if finished_sequence is not None and finished_sequence < 0:
            raise ValueError("Tool finished_sequence 不能为负数")

        run = await self._lock_run(
            run_id=run_id,
            request_id=request_id,
            thread_id=thread_id,
            worker_id=worker_id,
        )
        message = await self._get(run_id, operation_id)
        if message is None:
            raise ValueError("Tool terminal 缺少对应的 start 事实")
        self._require_same_owner(message, conversation_id=run.conversation_id, request_id=request_id)

        metadata = dict(message.extra_metadata or {})
        if message.execution_status == execution_status:
            if (
                message.content != content
                or metadata.get("error_message") != error_message
                or _canonical_tool_output(metadata.get("output")) != _canonical_tool_output(output)
            ):
                raise ValueError("已关闭 Tool 审计事实不能被不同结果覆盖")
            return message
        if message.execution_status != "running":
            raise ValueError(f"Tool 审计事实不能从 {message.execution_status} 转为 {execution_status}")

        tool_call = await self._require_compatibility_tool_call(metadata, operation_id)

        message.content = content
        message.finished_at = message.finished_at or finished_at
        if duration_ms is not None:
            message.duration_ms = duration_ms
        message.execution_status = execution_status
        metadata["output"] = output
        metadata["error_message"] = error_message
        if finished_sequence is not None:
            metadata["finished_sequence"] = finished_sequence
        message.extra_metadata = metadata

        tool_call.tool_output = content or None
        tool_call.status = tool_call_status
        tool_call.error_message = error_message
        await self.db.flush()
        await self.db.refresh(message)
        return message

    async def _lock_run(self, *, run_id: str, request_id: str, thread_id: str, worker_id: str):
        run = await self.run_repo.lock_output_persistence(
            run_id,
            worker_id=worker_id,
            conversation_thread_id=thread_id,
            request_id=request_id,
        )
        if run is None:
            raise ValueError(f"AgentRun 不存在: {run_id}")
        return run

    async def _get(self, run_id: str, operation_id: str) -> Message | None:
        result = await self.db.execute(
            select(Message).where(
                Message.run_id == run_id,
                Message.operation_id == operation_id,
                Message.message_type == TOOL_AUDIT_MESSAGE_TYPE,
            )
        )
        return result.scalar_one_or_none()

    async def _get_tool_call_for_message(self, message_id: int, operation_id: str) -> ToolCall | None:
        result = await self.db.execute(
            select(ToolCall).where(
                ToolCall.message_id == message_id,
                ToolCall.langgraph_tool_call_id == operation_id,
            )
        )
        return result.scalar_one_or_none()

    async def _find_source_model_message(self, run: AgentRun, tool_call_id: str) -> Message | None:
        """在当前 Run 及合法 resume 祖先中查找 ToolCall 声明。"""
        source_run_ids = await self._source_run_ids(run)
        result = await self.db.execute(
            select(Message)
            .where(
                Message.run_id.in_(source_run_ids),
                Message.role == "assistant",
                Message.operation_id.is_not(None),
                Message.message_type == MODEL_AUDIT_MESSAGE_TYPE,
            )
            .order_by(Message.created_at.desc(), Message.sequence.desc(), Message.id.desc())
        )
        for message in result.scalars().all():
            metadata = message.extra_metadata if isinstance(message.extra_metadata, dict) else {}
            tool_calls = metadata.get("tool_calls")
            if isinstance(tool_calls, list) and any(
                isinstance(item, dict) and str(item.get("id") or "") == tool_call_id for item in tool_calls
            ):
                return message
        return None

    async def _source_run_ids(self, run: AgentRun) -> list[str]:
        """返回同 Conversation 内无环的 resume 来源链。"""
        source_run_ids = [run.id]
        seen = {run.id}
        parent_id = run.created_by_run_id if run.run_type == "resume" else None
        while parent_id:
            if parent_id in seen:
                raise ValueError("Resume Run ancestry 存在循环")
            parent = await self.db.get(AgentRun, parent_id)
            if parent is None or parent.conversation_id != run.conversation_id:
                raise ValueError("Resume Run ancestry 与当前 conversation 不一致")
            source_run_ids.append(parent.id)
            seen.add(parent.id)
            parent_id = parent.created_by_run_id if parent.run_type == "resume" else None
        return source_run_ids

    async def _require_compatibility_tool_call(
        self,
        metadata: dict[str, Any],
        operation_id: str,
    ) -> ToolCall:
        """读取并校验审计绑定的兼容 ToolCall。"""
        tool_call_id = metadata.get("compatibility_tool_call_id")
        tool_call = await self.db.get(ToolCall, tool_call_id) if isinstance(tool_call_id, int) else None
        if tool_call is None or tool_call.langgraph_tool_call_id != operation_id:
            raise ValueError("ToolMessage 缺少 ToolCall 兼容投影")
        return tool_call

    @staticmethod
    def _require_same_owner(message: Message, *, conversation_id: int, request_id: str) -> None:
        if (
            message.conversation_id != conversation_id
            or message.request_id != request_id
            or message.role != "tool"
            or message.message_type != TOOL_AUDIT_MESSAGE_TYPE
        ):
            raise ValueError("Tool 审计消息必须属于同一 Run、request 和 conversation")

    @staticmethod
    def _require_same_start(
        message: Message,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        sequence: int,
    ) -> None:
        metadata = message.extra_metadata if isinstance(message.extra_metadata, dict) else {}
        if (
            metadata.get("tool_name") != tool_name
            or metadata.get("input") != tool_input
            or message.sequence != sequence
        ):
            raise ValueError("重复 Tool start 与已持久化事实不一致")


def _canonical_tool_output(output: Any) -> Any:
    """忽略 LangGraph 写入 State 时补充的 ToolMessage id/name，其余原始输出必须一致。"""
    if not isinstance(output, dict):
        return output
    return {key: value for key, value in output.items() if key not in {"id", "name"}}
