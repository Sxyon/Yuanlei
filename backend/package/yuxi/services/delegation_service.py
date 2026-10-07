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

from fastapi import HTTPException
from sqlalchemy import select
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
from yuxi.repositories.governance_repository import GovernanceRepository
from yuxi.repositories.project_agent_repository import ProjectAgentRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.storage.postgres.models_business import ChannelDelegation, Project, ProjectWorkTask, User
from yuxi.utils import logger
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

DEFAULT_LEASE_SECONDS = 120
SANDBOX_EXECUTOR_KEYS = ("opencode", "codex")
_UNSET = object()


def _serialize(row: ChannelDelegation, *, capabilities: dict[str, bool] | None = None) -> dict:
    """委派事实的统一读模型：同时呈现本地状态与远端只读投影。"""
    result_json = row.result_json or {}
    return {
        "id": row.id,
        "operation_id": row.operation_id,
        "context_recorded": row.context_snapshot is not None,
        "project_id": row.project_id,
        "executor_key": row.executor_key,
        "task": row.task,
        "governance_task_id": (row.request_json or {}).get("governance_task_id"),
        "work_task_id": row.work_task_id,
        "source_topic_id": row.source_topic_id,
        "source_decision_id": row.source_decision_id,
        "source_decision_revision": row.source_decision_revision,
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

    async def dispatch_project_task(self, *, project_id: str, task_id: str, executor_key: str, user: User) -> dict:
        """旧建议入口只提示纳入，既有委派继续查询和回收。"""
        project = await ProjectRepository(self.db).get_active_selectable_for_user(project_id, str(user.uid))
        task = await GovernanceRepository(self.db).get_task(task_id=task_id)
        if project is None or task is None or task.project_id != project_id:
            raise HTTPException(404, detail="工作建议不存在")
        mapping = await GovernanceRepository(self.db).admission(task_id)
        raise HTTPException(
            409,
            detail={
                "code": "formal_work_required",
                "message": "请纳入正式工作后从工作详情发起执行",
                "work_task_id": mapping[0].work_task_id if mapping else None,
            },
        )

    async def dispatch_work_task(
        self,
        *,
        project_id: str,
        task_id: str,
        executor_key: str,
        user: User,
        agent_slug: str | None = None,
        context: dict | None = None,
    ) -> dict:
        """从正式工作校验执行者与当前来源，委派到项目专属沙盒。"""
        from yuxi.agents.backends.sandbox.provider import SandboxScope
        from yuxi.repositories.agent_repository import AgentRepository, user_can_manage_agent

        if executor_key not in SANDBOX_EXECUTOR_KEYS:
            raise HTTPException(status_code=422, detail={"code": "invalid_executor", "message": "仅支持本地编码执行器"})
        project = await ProjectRepository(self.db).lock_active_selectable_for_user(project_id, str(user.uid))
        if project is None:
            raise HTTPException(status_code=404, detail="Project 不存在")
        from yuxi.repositories.project_work_repository import ProjectWorkRepository

        task = await ProjectWorkRepository(self.db, project_id=project_id, uid=str(user.uid)).get_task(
            task_id, lock=True
        )
        if task is None or task.project_id != project.id:
            raise HTTPException(status_code=404, detail="任务不存在")
        agent_slug = agent_slug or task.primary_owner_agent_slug
        if task.status in {"done", "cancelled"} or not agent_slug:
            raise HTTPException(
                status_code=409, detail={"code": "task_not_ready", "message": "请为未结束的正式工作选择项目数字员工"}
            )
        binding = await ProjectAgentRepository(self.db).get(project.id, agent_slug)
        agent = await AgentRepository(self.db).get_visible_by_slug(slug=agent_slug, user=user, kind="main")
        if binding is None or agent is None:
            raise HTTPException(status_code=409, detail={"code": "agent_unbound", "message": "项目数字员工绑定已失效"})
        if not user_can_manage_agent(user, agent):
            raise HTTPException(status_code=403, detail="需要该项目数字员工的管理权限")

        from yuxi.services.coding_execution_service import coding_agent_config_snapshot

        agent_config = {**(agent.config_json or {}), **(binding.config_overrides or {})}
        agent_config.update(coding_agent_config_snapshot(agent.config_json, binding.config_overrides))
        enabled_executors = (agent_config.get("coding") or {}).get("executors")
        if not isinstance(enabled_executors, list) or executor_key not in enabled_executors:
            raise HTTPException(
                status_code=422,
                detail={"code": "executor_not_enabled", "message": "该数字员工未启用所选执行器，请选择已配置的执行器"},
            )

        uid = str(user.uid)
        scope = SandboxScope.agent_project(uid=uid, agent_slug=agent.slug, project_id=project.id)
        prompt = task.title if not task.description else f"{task.title}\n\n{task.description}"
        return await self.dispatch(
            executor_key=executor_key,
            request=DelegationRequest(
                operation_id="",
                project_id=project.id,
                task=prompt,
                metadata={
                    "uid": uid,
                    "runtime_scope_id": scope.cache_key,
                    "workdir_relative_path": project.workdir_path,
                    "agent_config": agent_config,
                    "work_task_id": task.id,
                    "context": context or {},
                },
            ),
            uid=uid,
        )

    async def dispatch(
        self,
        *,
        executor_key: str,
        request: DelegationRequest,
        uid: str | None = None,
    ) -> dict:
        """先持久化投递意图，再调用执行器；成功后写入句柄与远端引用。"""
        if uid is None:
            raise HTTPException(403, detail="新委派需要当前用户和正式工作归属")
        from yuxi.repositories.project_work_repository import ProjectWorkRepository
        from yuxi.storage.postgres.models_business import ProjectWorkExecution

        project = await ProjectRepository(self.db).lock_active_selectable_for_user(request.project_id, str(uid))
        if project is None:
            raise HTTPException(404, detail="项目不存在")
        work_id = request.metadata.get("work_task_id")
        if not work_id:
            raise HTTPException(409, detail={"code": "formal_work_required", "message": "请选择正式工作后发起委派"})
        work = await ProjectWorkRepository(self.db, project_id=request.project_id, uid=str(uid)).get_task(
            work_id, lock=True
        )
        if work is None:
            raise HTTPException(404, detail="正式工作不存在")
        if work.status in {"done", "cancelled"}:
            raise HTTPException(409, detail={"code": "work_ended", "message": "正式工作已结束"})
        source = work
        execution_id = request.metadata.get("project_work_execution_id")
        if execution_id:
            source = await self.db.get(ProjectWorkExecution, execution_id)
            if (
                source is None
                or source.task_id != work.id
                or source.project_id != request.project_id
                or source.uid != str(uid)
            ):
                raise HTTPException(409, detail="当次执行与正式工作不一致")
        from yuxi.services.project_work_context_service import assemble_context
        from yuxi.repositories.project_work_context_repository import ProjectWorkContextRepository

        if execution_id:
            snapshot = source.context_snapshot
            if snapshot is None:
                raise HTTPException(409, detail="原执行未记录业务资料；请从正式工作新建执行，不推断旧依据")
        else:
            user = await ProjectWorkContextRepository(self.db, project.id).user(str(uid))
            if user is None:
                raise HTTPException(403, detail="当前用户不可用")
            snapshot = await assemble_context(
                db=self.db,
                user=user,
                project=project,
                task=work,
                **(request.metadata.get("context") or {}),
            )
        request = replace(request, task=request.task + "\n\n本次正式工作资料：\n" + snapshot["input_text"])
        request = replace(
            request,
            metadata={
                **request.metadata,
                "work_task_id": work.id,
                "source_topic_id": source.source_topic_id if execution_id else work.topic_id,
                "source_decision_id": source.source_decision_id,
                "source_decision_revision": source.source_decision_revision,
            },
        )
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
                "governance_task_id": request.metadata.get("governance_task_id"),
            },
            initiator_run_id=request.initiator_run_id,
            created_by=uid,
            now=now,
        )
        row.context_snapshot = snapshot
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
        if isinstance(executor, SandboxCodingExecutor):
            try:
                await executor.enqueue(handle, plan_only=bool(request.metadata.get("plan_only", False)))
            except Exception:
                logger.warning("Coding turn enqueue deferred to reconciliation: operation={}", operation_id)
        return _serialize(row, capabilities=executor.capabilities())

    async def status(self, *, operation_id: str, project_id: str | None = None) -> dict:
        """读取统一视图，并刷新远端状态的只读投影（不改写 dispatch_state）。"""
        row = await self._load(operation_id=operation_id, project_id=project_id)
        executor = self._executors.get(row.executor_key)
        if executor is not None and row.dispatch_state == "dispatched" and (row.external_ref or row.turn_id):
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
        if row.dispatch_state == "collecting" and row.lease_expires_at and row.lease_expires_at > now:
            raise DelegationError("结果正在回收，请稍后重试", error_code="delegation_collecting")
        self._claim(row, now=now, state="collecting")
        owner_token = row.owner_token
        await self.db.commit()
        await self.db.refresh(row)
        try:
            result = await executor.collect(self._handle(row))
        except DelegationError:
            current = await self.db.scalar(
                select(ChannelDelegation)
                .where(ChannelDelegation.operation_id == operation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if current and current.dispatch_state == "collecting" and current.owner_token == owner_token:
                current.dispatch_state = "dispatched"
                self._release(current)
                await self.db.commit()
            else:
                await self.db.rollback()
            raise
        project = await self.db.scalar(select(Project).where(Project.id == row.project_id).with_for_update())
        if row.work_task_id:
            await self.db.scalar(
                select(ProjectWorkTask).where(ProjectWorkTask.id == row.work_task_id).with_for_update()
            )
        row = await self.db.scalar(
            select(ChannelDelegation)
            .where(ChannelDelegation.operation_id == operation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row.dispatch_state != "collecting" or row.owner_token != owner_token:
            await self.db.rollback()
            raise DelegationError("回收租约已变更，请重试", error_code="delegation_owner_changed")
        artifact_path = None
        if result.text and workdir is not None:
            artifact_path = self._materialize(workdir, row.operation_id, result.text)
        row.result_summary = result.summary
        row.result_json = {
            "text": result.text,
            "artifacts": [dict(item) for item in result.artifacts],
            "usage": dict(result.usage),
        }
        row.artifact_path = artifact_path
        if result.remote_status:
            row.remote_status = result.remote_status
            row.remote_status_synced_at = now
        row.dispatch_state = "reclaimed"
        row.owner_token = None
        row.lease_expires_at = None
        row.error_code = result.error_code
        if (
            project is not None
            and row.work_task_id
            and result.remote_status == ("done" if row.executor_key == "multica" else "completed")
            and not result.error_code
        ):
            from yuxi.services.project_work_result_service import import_execution_result

            summary = (result.text or result.summary or "").strip()
            if summary:
                evidence = [
                    {"kind": "url", "value": item["url"]}
                    for item in result.artifacts
                    if item.get("kind") == "url" and item.get("url")
                ]
                if artifact_path and workdir is not None:
                    evidence.append({"kind": "file", "value": "/" + artifact_path})
                await import_execution_result(
                    db=self.db,
                    project=project,
                    source=row,
                    summary=summary,
                    evidence=evidence,
                    output_fact={
                        "operation_id": row.operation_id,
                        "session_id": row.session_id,
                        "turn_id": row.turn_id,
                        "external_ref": row.external_ref,
                        "artifacts": [dict(item) for item in result.artifacts],
                    },
                )
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
        operation_ids = [row.operation_id for row in await self.repo.list_unsettled_leased(now=now, limit=int(limit))]
        counts = {"redispatched": 0, "released": 0, "reprojected": 0, "failed": 0}
        for operation_id in operation_ids:
            row = await self.repo.get_by_operation_id(operation_id=operation_id, for_update=True)
            if row is None or row.dispatch_state not in {"pending", "dispatched", "collecting"}:
                continue
            if row.lease_expires_at is not None and row.lease_expires_at >= now:
                continue
            if row.dispatch_state == "pending":
                row = await self._converge_pending(row, now=now, counts=counts)
            elif row.dispatch_state == "collecting":
                row.dispatch_state = "dispatched"
                self._release(row)
                counts["released"] += 1
            else:  # dispatched：刷新远端只读投影并释放陈旧租约
                await self._converge_dispatched(row, now=now, counts=counts)
            await self.db.commit()
            await self.db.refresh(row)
        return counts

    async def _converge_pending(self, row: ChannelDelegation, *, now, counts: dict[str, int]) -> ChannelDelegation:
        owner_token = row.owner_token
        executor = self._executors.get(row.executor_key)
        if executor is None:
            self._release(row)
            return row
        try:
            handle = await executor.dispatch(self._request_from_row(row))
        except Exception as exc:
            operation_id = row.operation_id
            await self.db.rollback()
            row = await self.repo.get_by_operation_id(operation_id=operation_id, for_update=True)
            if row is None:
                raise DelegationNotFoundError(f"委派操作不存在: {operation_id}")
            if row.dispatch_state != "pending" or row.owner_token != owner_token:
                return row
            row.error_code = (
                "sandbox_policy_unsupported"
                if isinstance(exc, DelegationError) and exc.error_code == "sandbox_policy_unsupported"
                else "executor_dispatch_failed"
            )
            if row.error_code == "sandbox_policy_unsupported":
                row.dispatch_state = "failed"
            row.last_error_at = now
            self._release(row)
            counts["failed"] += 1
        else:
            self._apply_handle(row, handle, now=now)
            if isinstance(executor, SandboxCodingExecutor):
                await self.db.commit()
                try:
                    await executor.enqueue(
                        handle, plan_only=bool(self._request_from_row(row).metadata.get("plan_only", False))
                    )
                except Exception:
                    logger.warning("Coding turn enqueue deferred to reconciliation: operation={}", row.operation_id)
            counts["redispatched"] += 1
        return row

    async def _converge_dispatched(self, row: ChannelDelegation, *, now, counts: dict[str, int]) -> None:
        executor = self._executors.get(row.executor_key)
        if executor is not None and (row.external_ref or row.turn_id):
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
        operation_id = row.operation_id
        owner_token = row.owner_token
        await self.db.rollback()
        pending = await self.repo.get_by_operation_id(operation_id=operation_id, for_update=True)
        if pending is None:
            raise DelegationNotFoundError(f"委派操作不存在: {operation_id}")
        if pending.dispatch_state != "pending" or pending.owner_token != owner_token:
            return
        pending.error_code = error_code
        if error_code == "sandbox_policy_unsupported":
            pending.dispatch_state = "failed"
        pending.last_error_at = now
        self._release(pending)
        await self.db.commit()
        await self.db.refresh(pending)

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
