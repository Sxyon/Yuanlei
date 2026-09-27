"""沙盒编码执行器：把 codex/opencode 套进统一可委派接口（yuanlei 域）。

沿用 `coding_sessions` / `coding_session_turns` 作为唯一会话与执行事实，不新增平行
会话表；句柄绑定被委派的 `session_id` 与那一轮 `turn_id`，`collect` 只回收该轮。
多轮续接仍走既有 `coding_*` 工具，本适配器不提供 resume/cancel/streaming。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.coding.credentials import VALID_EXECUTORS
from yuxi.delegation.contracts import (
    DelegationError,
    DelegationHandle,
    DelegationRequest,
    DelegationResult,
)

EnqueueTurn = Callable[..., Awaitable[None]]


async def _default_enqueue(*, session_id: str, turn_id: str, plan_only: bool = False) -> None:
    """默认把 pending turn 投递给 worker。"""
    from yuxi.services.coding_execution_service import enqueue_coding_turn

    await enqueue_coding_turn(session_id=session_id, turn_id=turn_id, plan_only=plan_only)


class SandboxCodingExecutor:
    """opencode / codex 的委派适配器；复用 CodingExecutionService 与会话仓储。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        executor_key: str,
        enqueue: EnqueueTurn | None = None,
    ):
        if executor_key not in VALID_EXECUTORS:
            raise DelegationError(f"unsupported sandbox executor: {executor_key!r}", error_code="invalid_executor")
        self.key = executor_key
        self.db = db
        self._enqueue = enqueue or _default_enqueue

    def capabilities(self) -> dict[str, bool]:
        """沙盒有稳定多轮入口且产物落在 Workdir 内。"""
        return {"multi_turn": True, "remote_artifacts": False}

    async def dispatch(self, request: DelegationRequest) -> DelegationHandle:
        """创建编码会话并排队被委派的那一轮，返回绑定 session/turn 的句柄。"""
        from yuxi.agents.skills.service import refresh_user_skill_projection_async
        from yuxi.services.coding_execution_service import (
            CodingExecutionService,
            effective_coding_agent_config_snapshot,
        )
        from yuxi.services.sandbox_lifecycle_service import resolve_agent_sandbox_policy

        metadata = request.metadata or {}
        uid = str(metadata.get("uid") or "")
        runtime_scope_id = str(metadata.get("runtime_scope_id") or "")
        workdir_relative_path = str(metadata.get("workdir_relative_path") or "")
        agent_config = metadata.get("agent_config")
        conversation_id = metadata.get("conversation_id")
        plan_only = bool(metadata.get("plan_only", False))
        if not uid or not runtime_scope_id or not workdir_relative_path:
            raise DelegationError("沙盒委派缺少运行范围", error_code="sandbox_scope_missing")

        service = CodingExecutionService(
            self.db,
            uid=uid,
            thread_id=str(metadata.get("thread_id") or runtime_scope_id),
            runtime_scope_id=runtime_scope_id,
            workdir_relative_path=workdir_relative_path,
        )
        if service.scope.uid != uid or service.scope.project_id != request.project_id:
            raise DelegationError("沙盒委派范围与项目不一致", error_code="sandbox_scope_mismatch")
        policy = await resolve_agent_sandbox_policy(
            db=self.db,
            agent_config=agent_config,
            agent_slug=service.scope.agent_slug or "",
            project_id=service.scope.project_id or "",
        )
        if not policy.is_dedicated or policy.lifecycle not in {"persistent", "resident"}:
            raise DelegationError(
                "沙盒委派需要 persistent/resident 专属沙盒",
                error_code="sandbox_policy_unsupported",
            )

        await refresh_user_skill_projection_async(uid)
        await service.prepare(agent_config)
        session = await service.sessions.create_session(
            uid=uid,
            project_id=service.scope.project_id or "",
            runtime_scope_id=service.scope.cache_key,
            executor=self.key,
            workdir_path=workdir_relative_path,
            title=request.task.strip()[:120] or None,
            policy={
                "executor": self.key,
                "agent_config": await effective_coding_agent_config_snapshot(
                    self.db,
                    agent_config=agent_config,
                    agent_slug=service.scope.agent_slug or "",
                    project_id=service.scope.project_id or "",
                ),
            },
            budget=request.budget or None,
            conversation_id=conversation_id,
            parent_run_id=request.initiator_run_id,
        )
        session.executor = self.key
        turn = await service.sessions.queue_turn(
            session,
            request_text=request.task,
            plan_only=plan_only,
            enqueueing_run_id=request.initiator_run_id,
        )
        return DelegationHandle(
            operation_id=request.operation_id,
            executor_key=self.key,
            session_id=session.id,
            turn_id=turn.id,
        )

    async def enqueue(self, handle: DelegationHandle, *, plan_only: bool = False) -> None:
        """在委派句柄和编码 turn 同事务提交后发布队列消息。"""
        if handle.session_id and handle.turn_id:
            await self._enqueue(session_id=handle.session_id, turn_id=handle.turn_id, plan_only=plan_only)

    async def status(self, handle: DelegationHandle) -> str | None:
        """读取被委派那一轮 turn 的只读状态投影。"""
        from yuxi.repositories.coding_session_repository import CodingSessionRepository

        if not handle.turn_id:
            return None
        turn = await CodingSessionRepository(self.db).get_turn(handle.turn_id)
        return turn.status if turn is not None else None

    async def collect(self, handle: DelegationHandle) -> DelegationResult:
        """回收被委派那一轮的结果，不读取相邻 turn。"""
        from yuxi.repositories.coding_session_repository import CodingSessionRepository

        if not handle.turn_id:
            raise DelegationError("沙盒委派句柄缺少 turn_id", error_code="delegation_handle_invalid")
        turn = await CodingSessionRepository(self.db).get_turn(handle.turn_id)
        if turn is None:
            raise DelegationError("编码 turn 不存在", error_code="coding_turn_not_found")
        if turn.status in {"pending", "running"}:
            raise DelegationError("编码 turn 尚未终结", error_code="delegation_not_ready")
        summary = turn.result_summary
        return DelegationResult(
            summary=summary,
            text=summary,
            artifacts=(),
            usage=turn.usage_json or {},
            remote_status=turn.status,
            error_code=turn.error_code,
        )
