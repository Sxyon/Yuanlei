"""元垒外部执行器委派编排：适配器注册、委派事实、租约与统一读模型（yuanlei 域）。

只做编排，不重实现任何执行基底：codex/opencode 的执行与会话事实仍归
`CodingExecutionService` 与 `coding_sessions`；Multica 的传输收敛在适配器内。
投递意图先持久化，本地 `dispatch_state` 与远端 `remote_status` 只读投影分离，
结果只引用发起 Run，不新增 `agent_runs` 行。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import replace
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.delegation.contracts import (
    DelegatedExecutor,
    DelegationError,
    DelegationHandle,
    DelegationNotFoundError,
    DelegationRequest,
    ExecutorUnavailableError,
)
from yuxi.delegation.multica import MulticaExecutor, build_multica_client_from_env
from yuxi.delegation.sandbox import SandboxCodingExecutor
from yuxi.repositories.channel_delegation_repository import ChannelDelegationRepository
from yuxi.storage.postgres.models_business import ChannelDelegation
from yuxi.utils import logger
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

DEFAULT_LEASE_SECONDS = 120
SANDBOX_EXECUTOR_KEYS = ("opencode", "codex")
_UNSET = object()


def _serialize(row: ChannelDelegation, *, capabilities: dict[str, bool] | None = None) -> dict:
    """委派事实的统一读模型：同时呈现本地状态与远端只读投影。"""
    result_json = row.result_json or {}
    return {
        "operation_id": row.operation_id,
        "project_id": row.project_id,
        "executor_key": row.executor_key,
        "task": row.task,
        "initiator_run_id": row.initiator_run_id,
        "session_id": row.session_id,
        "turn_id": row.turn_id,
        "external_ref": row.external_ref,
        "external_url": row.external_url,
        "dispatch_state": row.dispatch_state,
        "attempts": row.attempts,
        "remote_status": row.remote_status,
        "remote_status_synced_at": format_utc_datetime(row.remote_status_synced_at),
        "result": {
            "summary": row.result_summary,
            "artifacts": result_json.get("artifacts") or [],
            "usage": result_json.get("usage") or {},
        },
        "artifact_path": row.artifact_path,
        "error_code": row.error_code,
        "last_error_at": format_utc_datetime(row.last_error_at),
        "capabilities": capabilities or {},
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


class DelegationService:
    """按适配器注册表编排委派、查询与回收；ds 事务由本服务按步骤提交。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        executors: Iterable[DelegatedExecutor] = (),
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ):
        self.db = db
        self.repo = ChannelDelegationRepository(db)
        self.lease_seconds = int(lease_seconds)
        self._executors: dict[str, DelegatedExecutor] = {}
        for executor in executors:
            self.register(executor)

    @classmethod
    def build_default(
        cls,
        db: AsyncSession,
        *,
        multica_client=_UNSET,
        sandbox_enqueue=None,
    ) -> DelegationService:
        """装配默认执行器：沙盒 codex/opencode，以及有凭据时注册的 Multica。"""
        service = cls(db)
        for key in SANDBOX_EXECUTOR_KEYS:
            service.register(SandboxCodingExecutor(db, executor_key=key, enqueue=sandbox_enqueue))
        client = build_multica_client_from_env() if multica_client is _UNSET else multica_client
        if client is not None:
            service.register(MulticaExecutor(client))
        return service

    def register(self, executor: DelegatedExecutor) -> None:
        """按 executor key 注册适配器。"""
        self._executors[str(executor.key)] = executor

    def registered_keys(self) -> tuple[str, ...]:
        return tuple(self._executors)

    def capabilities(self, executor_key: str) -> dict[str, bool]:
        executor = self._executors.get(str(executor_key))
        return executor.capabilities() if executor is not None else {}

    def _require_executor(self, executor_key: str) -> DelegatedExecutor:
        executor = self._executors.get(str(executor_key))
        if executor is None:
            raise ExecutorUnavailableError(f"执行器未注册或不可用: {executor_key}")
        return executor

    async def dispatch(
        self,
        *,
        executor_key: str,
        request: DelegationRequest,
        uid: str | None = None,
    ) -> dict:
        """先持久化投递意图，再调用执行器；成功后写入句柄与远端引用。"""
        executor = self._require_executor(executor_key)
        operation_id = str(request.operation_id or uuid.uuid4().hex)
        request = replace(request, operation_id=operation_id)
        now = utc_now_naive()
        row = await self.repo.add_delegation(
            operation_id=operation_id,
            project_id=request.project_id,
            executor_key=executor_key,
            task=request.task,
            request_json={
                "context_refs": [dict(ref) for ref in request.context_refs],
                "budget": dict(request.budget),
                "metadata": dict(request.metadata),
            },
            initiator_run_id=request.initiator_run_id,
            created_by=uid,
            now=now,
        )
        self._claim(row, now=now)
        await self.db.commit()
        await self.db.refresh(row)
        try:
            handle = await executor.dispatch(request)
        except DelegationError as exc:
            await self._record_error(row, exc.error_code, now=utc_now_naive())
            raise
        except Exception as exc:  # 结构性失败不静默：落错误码并保持可重试
            await self._record_error(row, "executor_dispatch_failed", now=utc_now_naive())
            raise DelegationError(str(exc), error_code="executor_dispatch_failed") from exc
        await self.db.refresh(row)
        self._apply_handle(row, handle, now=utc_now_naive())
        await self.db.commit()
        await self.db.refresh(row)
        return _serialize(row, capabilities=executor.capabilities())

    async def status(self, *, operation_id: str, project_id: str | None = None) -> dict:
        """读取统一视图，并刷新远端状态的只读投影（不改写 dispatch_state）。"""
        row = await self._load(operation_id=operation_id, project_id=project_id)
        executor = self._executors.get(row.executor_key)
        if executor is not None and row.dispatch_state == "dispatched" and row.external_ref:
            try:
                remote = await executor.status(self._handle(row))
            except Exception:
                logger.warning("Failed to refresh delegation remote status: operation={}", row.operation_id)
            else:
                if remote is not None and remote != row.remote_status:
                    row.remote_status = remote
                    row.remote_status_synced_at = utc_now_naive()
                    await self.db.commit()
                    await self.db.refresh(row)
        return _serialize(row, capabilities=executor.capabilities() if executor is not None else None)

    async def collect(
        self,
        *,
        operation_id: str,
        project_id: str | None = None,
        workdir=None,
    ) -> dict:
        """回收被委派操作的结果；可选把文本结果物化在 Workdir 边界内。"""
        row = await self.repo.get_by_operation_id(operation_id=operation_id, for_update=True)
        if row is None or (project_id is not None and row.project_id != str(project_id)):
            raise DelegationNotFoundError(f"委派操作不存在: {operation_id}")
        if row.dispatch_state == "reclaimed":
            return _serialize(row, capabilities=self.capabilities(row.executor_key))
        if row.dispatch_state not in {"dispatched", "collecting"}:
            raise DelegationError(f"当前状态不可回收: {row.dispatch_state}", error_code="delegation_state_invalid")
        executor = self._require_executor(row.executor_key)
        now = utc_now_naive()
        self._claim(row, now=now, state="collecting")
        await self.db.commit()
        await self.db.refresh(row)
        result = await executor.collect(self._handle(row))
        artifact_path = None
        if result.text and workdir is not None:
            artifact_path = self._materialize(workdir, row.operation_id, result.text)
        row.result_summary = result.summary
        row.result_json = {"artifacts": [dict(item) for item in result.artifacts], "usage": dict(result.usage)}
        row.artifact_path = artifact_path
        if result.remote_status:
            row.remote_status = result.remote_status
            row.remote_status_synced_at = now
        row.dispatch_state = "reclaimed"
        row.owner_token = None
        row.lease_expires_at = None
        row.error_code = result.error_code
        await self.db.commit()
        await self.db.refresh(row)
        return _serialize(row, capabilities=executor.capabilities())

    async def list_delegations(self, *, project_id: str) -> list[dict]:
        """列出项目内委派事实的统一视图。"""
        rows = await self.repo.list_for_project(project_id=project_id)
        return [_serialize(row, capabilities=self.capabilities(row.executor_key)) for row in rows]

    async def converge(self, *, limit: int = 50) -> dict[str, int]:
        """确定性收敛非终态委派：重投 pending、复位 collecting、刷新远端投影。"""
        now = utc_now_naive()
        rows = await self.repo.list_unsettled_leased(now=now, limit=int(limit))
        counts = {"redispatched": 0, "released": 0, "reprojected": 0, "failed": 0}
        for row in rows:
            if row.dispatch_state == "pending":
                await self._converge_pending(row, now=now, counts=counts)
            elif row.dispatch_state == "collecting":
                row.dispatch_state = "dispatched"
                self._release(row)
                counts["released"] += 1
            else:  # dispatched：刷新远端只读投影并释放陈旧租约
                await self._converge_dispatched(row, now=now, counts=counts)
            await self.db.commit()
            await self.db.refresh(row)
        return counts

    async def _converge_pending(self, row: ChannelDelegation, *, now, counts: dict[str, int]) -> None:
        executor = self._executors.get(row.executor_key)
        if executor is None:
            self._release(row)
            return
        try:
            handle = await executor.dispatch(self._request_from_row(row))
        except Exception:
            row.error_code = "executor_dispatch_failed"
            row.last_error_at = now
            self._release(row)
            counts["failed"] += 1
        else:
            self._apply_handle(row, handle, now=now)
            counts["redispatched"] += 1

    async def _converge_dispatched(self, row: ChannelDelegation, *, now, counts: dict[str, int]) -> None:
        executor = self._executors.get(row.executor_key)
        if executor is not None and row.external_ref:
            try:
                remote = await executor.status(self._handle(row))
            except Exception:
                logger.warning("Failed to refresh delegation during convergence: operation={}", row.operation_id)
            else:
                if remote is not None:
                    row.remote_status = remote
                    row.remote_status_synced_at = now
                counts["reprojected"] += 1
        self._release(row)

    async def _load(self, *, operation_id: str, project_id: str | None) -> ChannelDelegation:
        row = await self.repo.get_by_operation_id(operation_id=operation_id)
        if row is None or (project_id is not None and row.project_id != str(project_id)):
            raise DelegationNotFoundError(f"委派操作不存在: {operation_id}")
        return row

    async def _record_error(self, row: ChannelDelegation, error_code: str, *, now) -> None:
        row.error_code = error_code
        row.last_error_at = now
        self._release(row)
        await self.db.commit()
        await self.db.refresh(row)

    def _claim(self, row: ChannelDelegation, *, now, state: str | None = None) -> None:
        row.owner_token = uuid.uuid4().hex
        row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
        row.attempts = int(row.attempts or 0) + 1
        if state is not None:
            row.dispatch_state = state

    @staticmethod
    def _release(row: ChannelDelegation) -> None:
        row.owner_token = None
        row.lease_expires_at = None

    def _apply_handle(self, row: ChannelDelegation, handle: DelegationHandle, *, now) -> None:
        row.session_id = handle.session_id
        row.turn_id = handle.turn_id
        row.external_ref = handle.external_ref
        row.external_url = handle.external_url
        if handle.remote_status:
            row.remote_status = handle.remote_status
            row.remote_status_synced_at = now
        row.dispatch_state = "dispatched"
        row.error_code = None
        self._release(row)

    @staticmethod
    def _handle(row: ChannelDelegation) -> DelegationHandle:
        return DelegationHandle(
            operation_id=row.operation_id,
            executor_key=row.executor_key,
            session_id=row.session_id,
            turn_id=row.turn_id,
            external_ref=row.external_ref,
            external_url=row.external_url,
        )

    @staticmethod
    def _request_from_row(row: ChannelDelegation) -> DelegationRequest:
        payload = row.request_json or {}
        return DelegationRequest(
            operation_id=row.operation_id,
            project_id=row.project_id,
            task=row.task,
            initiator_run_id=row.initiator_run_id,
            context_refs=tuple(payload.get("context_refs") or ()),
            budget=dict(payload.get("budget") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )

    @staticmethod
    def _materialize(workdir, operation_id: str, text: str) -> str:
        """把远端文本结果写入 Workdir 内 `.yuanlei/delegations/<op>/result.md`。"""
        rel_dir = f".yuanlei/delegations/{operation_id}"
        for parent, name in (("/", ".yuanlei"), ("/.yuanlei", "delegations"), ("/.yuanlei/delegations", operation_id)):
            try:
                workdir.create_directory(parent, name)
            except FileExistsError:
                pass
        relative = f"{rel_dir}/result.md"
        workdir.replace_file(f"/{relative}", text.encode("utf-8"))
        return relative


async def reconcile_delegations() -> dict[str, int]:
    """确定性收敛非终态委派：重投 pending、复位 collecting、刷新远端投影。"""
    from yuxi.storage.postgres.manager import pg_manager

    async with pg_manager.get_async_session_context() as db:
        service = DelegationService.build_default(db)
        return await service.converge()
