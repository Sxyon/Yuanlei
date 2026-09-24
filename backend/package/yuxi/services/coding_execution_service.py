"""编码会话执行用例：在专属沙盒内运行 headless turn 并持久化。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.agents.backends.paths import runtime_workdir_path
from yuxi.agents.backends.sandbox import SandboxScope
from yuxi.agents.backends.sandbox.backend import ProvisionerSandboxBackend
from yuxi.coding.adapters import (
    CodingTurnRequest,
    NormalizedEvent,
    extract_turn_result,
    get_coding_adapter,
)
from yuxi.config import get_int_env
from yuxi.repositories.coding_session_repository import CodingSessionRepository
from yuxi.repositories.project_agent_repository import ProjectAgentRepository
from yuxi.services.coding_credential_service import (
    CodingCredentialService,
)
from yuxi.services.coding_session_service import (
    SESSION_TERMINAL_STATUSES,
    CodingSessionService,
    CodingSessionStateError,
)
from yuxi.services.run_queue_service import (
    clear_coding_cancel_signal,
    coding_cancel_requested,
)
from yuxi.services.sandbox_lifecycle_service import (
    SandboxLifecycleService,
    resolve_agent_sandbox_policy,
)
from yuxi.services.sandbox_lease_service import SandboxLeaseService, sandbox_lease_seconds
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import AgentRun
from yuxi.utils.datetime_utils import utc_now_naive

DEFAULT_CODING_TURN_TIMEOUT_SECONDS = 600


def coding_turn_timeout_seconds() -> int:
    return max(60, get_int_env("SANDBOX_CODING_TURN_TIMEOUT_SECONDS", DEFAULT_CODING_TURN_TIMEOUT_SECONDS))


def coding_agent_config_snapshot(agent_config: dict | None, project_overrides: dict | None = None) -> dict:
    """固化异步恢复需要的非密、项目生效 coding/sandbox 配置块。"""
    source = agent_config if isinstance(agent_config, dict) else {}
    overrides = project_overrides if isinstance(project_overrides, dict) else {}
    snapshot: dict = {"_coding_effective_snapshot": True}
    for key in ("coding", "sandbox"):
        merged: dict = {}
        if isinstance((block := source.get(key)), dict):
            merged.update(block)
        if isinstance((override := overrides.get(key)), dict):
            merged.update(override)
        if merged:
            snapshot[key] = merged
    return snapshot


async def effective_coding_agent_config_snapshot(
    db: AsyncSession,
    *,
    agent_config: dict | None,
    agent_slug: str,
    project_id: str,
) -> dict:
    """在排队事务内读取并冻结项目生效配置，恢复时不再追随 live override。"""
    binding = await ProjectAgentRepository(db).get(str(project_id), str(agent_slug))
    overrides = binding.config_overrides if binding is not None else None
    return coding_agent_config_snapshot(agent_config, overrides)


def _queued_plan_only(session, turn_id: str, fallback: bool = False) -> bool:
    marker = (session.policy_json or {}).get("pending_turn")
    if isinstance(marker, dict) and marker.get("id") == str(turn_id):
        return bool(marker.get("plan_only"))
    return bool(fallback)


def coding_turn_owner_prefix(turn_id: str) -> str:
    """生成可关联 turn 且满足数据库长度限制的 worker owner 前缀。"""
    digest = hashlib.sha256(str(turn_id).encode()).hexdigest()[:16]
    return f"coding-turn:{digest}:"


def _new_coding_turn_owner_id(turn_id: str) -> str:
    """每次投递生成独立 fencing owner，避免重复 job 互相释放租约。"""
    return f"{coding_turn_owner_prefix(turn_id)}{uuid.uuid4().hex[:16]}"


class CodingScopeUnsupportedError(RuntimeError):
    """编码执行需要专属（agent-project）沙盒作用域。"""

    error_code = "coding_scope_unsupported"


class CodingBudgetExceededError(RuntimeError):
    """会话 turn 数超过预算。"""

    error_code = "budget_exceeded"


class CodingTurnOwnershipLostError(RuntimeError):
    """异步 turn 已失去沙盒执行所有权，禁止继续写入结果。"""


@dataclass(frozen=True)
class _CliStateLayout:
    env: dict[str, str]
    prelude: str
    probe_dir: str


def _cli_state_layout(*, executor: str, session_id: str) -> _CliStateLayout:
    """按执行器给出把原生 CLI 状态持久化到 Workdir 的 env 与预置命令。"""
    base = f"/home/gem/user-data/agents/coding/{session_id}"
    if executor == "opencode":
        data_dir = f"{base}/data"
        cache_dir = f"{base}/cache"
        return _CliStateLayout(
            env={"XDG_DATA_HOME": data_dir, "XDG_CACHE_HOME": cache_dir},
            prelude=f"mkdir -p {shlex.quote(data_dir)} {shlex.quote(cache_dir)}",
            probe_dir=f"{data_dir}/opencode",
        )
    home = f"{base}/codex-home"
    quoted = shlex.quote(home)
    return _CliStateLayout(
        env={"CODEX_HOME": home},
        prelude=(f"mkdir -p {quoted} && cp -n /home/gem/.codex/config.toml {quoted}/config.toml 2>/dev/null || true"),
        probe_dir=home,
    )


@dataclass(frozen=True)
class CodingTurnOutcome:
    """一次 turn 的对外结果摘要。"""

    session_id: str
    turn_seq: int | None
    status: str
    executor: str
    output_text: str
    cli_session_ref: str | None
    usage: dict | None
    event_count: int
    resume_degraded: bool = False
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "turn_seq": self.turn_seq,
            "status": self.status,
            "executor": self.executor,
            "output_text": self.output_text,
            "cli_session_ref": self.cli_session_ref,
            "usage": self.usage or {},
            "event_count": self.event_count,
            "resume_degraded": self.resume_degraded,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


class CodingExecutionService:
    """在专属沙盒中执行编码 turn；db 事务由本服务按步骤提交。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        uid: str,
        thread_id: str,
        runtime_scope_id: str,
        workdir_relative_path: str,
        backend=None,
        provider=None,
    ):
        self.db = db
        self.uid = str(uid)
        self.thread_id = str(thread_id)
        self.workdir_relative_path = str(workdir_relative_path)
        self.scope = SandboxScope.from_runtime_scope(uid=self.uid, runtime_scope_id=runtime_scope_id)
        if self.scope.kind != "agent_project":
            raise CodingScopeUnsupportedError("coding execution requires a dedicated (agent-project) sandbox scope")
        self._backend = backend
        self._provider = provider
        self.sessions = CodingSessionService(db)

    @property
    def backend(self):
        if self._backend is None:
            self._backend = ProvisionerSandboxBackend(
                thread_id=self.scope.cache_key,
                uid=self.uid,
                workdir_path=self.workdir_relative_path,
                create_if_missing=False,
                scope=self.scope,
            )
        return self._backend

    async def _prepare(self, agent_config: dict | None) -> list[str]:
        """确保专属沙盒与凭据就绪，返回用于脱敏的密钥明文列表。"""
        frozen = bool((agent_config or {}).get("_coding_effective_snapshot"))
        config_project_id = None if frozen else self.scope.project_id
        policy = await resolve_agent_sandbox_policy(
            db=self.db,
            agent_config=agent_config,
            agent_slug=self.scope.agent_slug or "",
            project_id=config_project_id,
        )
        if not policy.is_dedicated:
            raise CodingScopeUnsupportedError("agent sandbox policy is not dedicated; coding execution is unavailable")
        credentials = CodingCredentialService(self.db)
        settings = await credentials.resolve_settings(
            agent_config=agent_config,
            agent_slug=self.scope.agent_slug or "",
            project_id=config_project_id,
        )
        environment = await credentials.build_coding_environment(
            uid=self.uid,
            executors=list(settings.executors),
        )
        await SandboxLifecycleService(self.db, provider=self._provider).ensure_ready(
            uid=self.uid,
            agent_slug=self.scope.agent_slug or "",
            project_id=self.scope.project_id or "",
            policy=policy,
            workdir_path=self.workdir_relative_path,
            credential_fingerprint=environment.fingerprint,
            env_overrides=environment.env,
        )
        return [value for value in environment.env.values() if value]

    async def prepare(self, agent_config: dict | None) -> list[str]:
        """公开的环境准备入口：异步入队前确保凭据与专属沙盒就绪。"""
        return await self._prepare(agent_config)

    async def terminate_cli_processes(self) -> None:
        """进程级取消：终止本沙盒内活跃的编码 CLI（前提是单 active turn）。"""
        command = "pkill -f 'opencode run' 2>/dev/null; pkill -f 'codex exec' 2>/dev/null; true"
        await asyncio.to_thread(self.backend.execute, command, timeout=15)

    async def run_turn(
        self,
        *,
        executor: str,
        task: str,
        plan_only: bool = False,
        session_id: str | None = None,
        agent_config: dict | None = None,
        budget: dict | None = None,
        conversation_id: int | None = None,
        parent_run_id: str | None = None,
    ) -> CodingTurnOutcome:
        repo = CodingSessionRepository(self.db)
        if session_id:
            session = await repo.get_for_update(session_id)
            if session is None or session.uid != self.uid:
                raise ValueError("coding session not found")
            self.validate_session_scope(session, conversation_id=conversation_id)
            if session.status != "idle":
                raise CodingSessionStateError(f"coding session is not idle: {session.status}")
        else:
            session = await self.sessions.create_session(
                uid=self.uid,
                project_id=self.scope.project_id or "",
                runtime_scope_id=self.scope.cache_key,
                executor=executor,
                workdir_path=self.workdir_relative_path,
                title=task.strip()[:120] or None,
                policy={
                    "executor": executor,
                    "agent_config": await effective_coding_agent_config_snapshot(
                        self.db,
                        agent_config=agent_config,
                        agent_slug=self.scope.agent_slug or "",
                        project_id=self.scope.project_id or "",
                    ),
                },
                budget=budget,
                conversation_id=conversation_id,
                parent_run_id=parent_run_id,
            )
        secrets = await self._prepare(agent_config)
        session.executor = str(executor)
        session.sandbox_id = self.scope.sandbox_id
        max_turns = int((session.budget_json or {}).get("max_turns") or 0)
        existing_turns = len(await repo.list_turns(session_id=session.id))
        if max_turns and existing_turns >= max_turns:
            message = f"coding session budget exceeded: max_turns={max_turns}"
            await self.sessions.transition(
                session, status="failed", error_code="budget_exceeded", error_message=message
            )
            await self.db.commit()
            raise CodingBudgetExceededError(message)
        turn = await self.sessions.start_turn(session, request_text=task)
        await self.db.commit()
        return await self._execute_turn_tail(
            session=session,
            turn=turn,
            executor=str(executor),
            task=task,
            plan_only=plan_only,
            secrets=secrets,
        )

    def validate_session_scope(self, session, *, conversation_id: int | None) -> None:
        """续轮必须仍属于当前 Conversation、Project、runtime scope 与 Workdir。"""
        if conversation_id is not None and session.conversation_id != int(conversation_id):
            raise CodingSessionStateError("coding session belongs to another conversation")
        if session.project_id != (self.scope.project_id or ""):
            raise CodingSessionStateError("coding session belongs to another project")
        if session.runtime_scope_id != self.scope.cache_key:
            raise CodingSessionStateError("coding session belongs to another runtime scope")
        if session.workdir_path != self.workdir_relative_path:
            raise CodingSessionStateError("coding session belongs to another workdir")

    async def _execute_turn_tail(
        self,
        *,
        session,
        turn,
        executor: str,
        task: str,
        plan_only: bool,
        secrets: list[str],
        ownership_guard: Callable[[], Awaitable[bool]] | None = None,
    ) -> CodingTurnOutcome:
        """执行既定 turn 的公共尾部：状态探测、命令执行、事件持久化与终态收敛。"""
        layout = _cli_state_layout(executor=session.executor, session_id=session.id)
        resume_degraded = False
        if session.cli_session_ref:
            probe = await asyncio.to_thread(
                self.backend.execute,
                f"test -d {shlex.quote(layout.probe_dir)} && echo __PRESENT__ || true",
            )
            if "__PRESENT__" not in str(getattr(probe, "output", "") or ""):
                resume_degraded = True
                session.cli_session_ref = None
                await self.sessions.repo.append_event(
                    session,
                    kind="resume_degraded",
                    payload={"reason": "cli_state_missing", "executor": session.executor},
                )
        adapter = get_coding_adapter(executor or session.executor)
        command = adapter.build_command(
            CodingTurnRequest(
                prompt=task,
                session_ref=session.cli_session_ref,
                plan_only=plan_only,
                workdir=runtime_workdir_path(self.workdir_relative_path),
                env=layout.env,
                prelude=layout.prelude,
            )
        )
        raw_output = ""
        exit_code = 0
        infra_error: str | None = None
        try:
            response = await asyncio.to_thread(self.backend.execute, command, timeout=coding_turn_timeout_seconds())
            raw_output = str(getattr(response, "output", "") or "")
            exit_code = int(getattr(response, "exit_code", 0) or 0)
        except Exception as exc:  # noqa: BLE001
            infra_error = f"sandbox execute failed: {exc}"

        events = adapter.parse_events(raw_output)
        if infra_error:
            events.append(NormalizedEvent("error", {"message": infra_error}))
        events = [NormalizedEvent(event.kind, _redact_event_payload(event.payload, secrets)) for event in events]
        result = extract_turn_result(events)
        if ownership_guard is not None and not await ownership_guard():
            await self.db.rollback()
            raise CodingTurnOwnershipLostError("coding turn sandbox lease is no longer active")
        await self.sessions.record_events(session, turn_id=turn.id, events=events)

        cancelled = await coding_cancel_requested(session.id)
        failed = bool(result.error or infra_error or exit_code != 0)
        summary = CodingCredentialService.redact(result.output_text[:2000], secrets)
        if cancelled:
            await self.sessions.repo.finish_turn(turn, status="cancelled", result_summary=summary, usage=result.usage)
            await self.sessions.repo.append_event(
                session,
                kind="turn_finished",
                turn_id=turn.id,
                payload={"seq": turn.seq, "status": "cancelled"},
            )
            await self.sessions.transition(session, status="cancelled")
        else:
            await self.sessions.finish_turn(
                session,
                turn,
                status="failed" if failed else "completed",
                result_summary=summary,
                usage=result.usage,
                error_code="executor_error" if failed else None,
                error_message=CodingCredentialService.redact(result.error or infra_error or "", secrets) or None,
                cli_session_ref=result.session_ref,
            )
        await clear_coding_cancel_signal(session.id)
        await self.db.commit()
        return CodingTurnOutcome(
            session_id=session.id,
            turn_seq=turn.seq,
            status="cancelled" if cancelled else session.status,
            executor=session.executor,
            output_text=summary,
            cli_session_ref=session.cli_session_ref,
            usage=result.usage,
            event_count=len(events),
            resume_degraded=resume_degraded,
            error_code=None if cancelled else ("executor_error" if failed else None),
            error_message=None if cancelled else (result.error or infra_error),
        )

    async def status(self, session_id: str, *, event_limit: int = 20) -> dict:
        repo = CodingSessionRepository(self.db)
        session = await repo.get(session_id)
        if session is None or session.uid != self.uid:
            raise ValueError("coding session not found")
        turns = await repo.list_turns(session_id=session.id)
        events = await repo.list_events(session_id=session.id, limit=event_limit)
        return {
            "session": {
                "id": session.id,
                "project_id": session.project_id,
                "conversation_id": session.conversation_id,
                "parent_run_id": session.parent_run_id,
                "runtime_scope_id": session.runtime_scope_id,
                "executor": session.executor,
                "status": session.status,
                "title": session.title,
                "cli_session_ref": session.cli_session_ref,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "terminal_at": session.terminal_at.isoformat() if session.terminal_at else None,
                "error_code": session.error_code,
            },
            "turns": [
                {
                    "seq": turn.seq,
                    "status": turn.status,
                    "summary": turn.result_summary,
                    "usage": turn.usage_json or {},
                    "started_at": turn.started_at.isoformat() if turn.started_at else None,
                }
                for turn in turns
            ],
            "events": [{"seq": event.seq, "kind": event.kind, "payload": event.payload_json} for event in events],
        }

    async def list_sessions(self, *, conversation_id: int | None = None) -> list[dict]:
        repo = CodingSessionRepository(self.db)
        if conversation_id is not None:
            sessions = await repo.list_for_conversation(conversation_id=conversation_id, uid=self.uid)
        else:
            sessions = await repo.list_for_uid(uid=self.uid)
        return [
            {
                "id": session.id,
                "executor": session.executor,
                "status": session.status,
                "title": session.title,
                "project_id": session.project_id,
                "created_at": session.created_at.isoformat() if session.created_at else None,
            }
            for session in sessions
        ]

    async def cancel(self, session_id: str) -> dict:
        repo = CodingSessionRepository(self.db)
        session = await repo.get_for_update(session_id)
        if session is None or session.uid != self.uid:
            raise ValueError("coding session not found")
        if session.status in SESSION_TERMINAL_STATUSES:
            raise CodingSessionStateError(f"coding session already terminal: {session.status}")
        await self.sessions.transition(session, status="cancelled")
        await self.db.commit()
        return {"session_id": session.id, "status": session.status}

    @staticmethod
    def summarize_for_tool(outcome: CodingTurnOutcome) -> str:
        return json.dumps(outcome.to_dict(), ensure_ascii=False)


async def _load_agent_config_for_session(db, session) -> dict | None:
    snapshot = (session.policy_json or {}).get("agent_config")
    if isinstance(snapshot, dict):
        return snapshot
    if not session.parent_run_id:
        return None
    from yuxi.repositories.agent_repository import AgentRepository

    run = await db.get(AgentRun, str(session.parent_run_id))
    if run is None:
        return None
    agent = await AgentRepository(db).get_by_slug(run.agent_slug)
    return agent.config_json if agent is not None else None


def _redact_event_payload(value, secrets: list[str]):
    """递归脱敏持久事件中的字符串值。"""
    if isinstance(value, str):
        return CodingCredentialService.redact(value, secrets)
    if isinstance(value, dict):
        return {key: _redact_event_payload(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_event_payload(item, secrets) for item in value]
    return value


async def run_coding_turn_job(
    *,
    session_id: str,
    turn_id: str,
    plan_only: bool = False,
    session_factory=None,
    provider=None,
    backend=None,
    lease_service=None,
) -> dict:
    """worker 后台执行已入队的 turn；重复执行与终态 turn 幂等跳过。"""
    factory = session_factory or pg_manager.get_async_session_context
    owner_id = _new_coding_turn_owner_id(turn_id)
    lease = lease_service or SandboxLeaseService()

    async with factory() as db:
        repo = CodingSessionRepository(db)
        session = await repo.get(session_id)
        if session is None:
            return {"status": "skipped", "reason": "session_missing"}
        turn = await repo.get_turn(turn_id)
        if turn is None:
            return {"status": "skipped", "reason": "turn_missing"}
        if turn.status != "pending":
            return {"status": "skipped", "reason": turn.status}
        if session.status in SESSION_TERMINAL_STATUSES:
            locked_session = await repo.get_for_update(session_id)
            locked_turn = await repo.get_turn_for_update(turn_id)
            if locked_session is not None and locked_turn is not None and locked_turn.status == "pending":
                await repo.finish_turn(locked_turn, status="cancelled", error_code="session_terminal")
                CodingSessionService(db).clear_pending_turn(locked_session, locked_turn.id)
                await db.commit()
            return {"status": "skipped", "reason": "session_terminal"}
        scope = SandboxScope.from_runtime_scope(uid=str(session.uid), runtime_scope_id=str(session.runtime_scope_id))
        if scope.kind != "agent_project":
            return {"status": "skipped", "reason": "coding_scope_unsupported"}

    await lease.acquire(
        uid=scope.uid,
        agent_slug=scope.agent_slug or "",
        project_id=scope.project_id or "",
        owner_kind="coding_session",
        owner_id=owner_id,
    )
    heartbeat_lost = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat_coding_turn_lease(lease=lease, scope=scope, owner_id=owner_id, lost=heartbeat_lost)
    )
    try:
        async with factory() as db:
            repo = CodingSessionRepository(db)
            session = await repo.get_for_update(session_id)
            turn = await repo.get_turn_for_update(turn_id)
            if session is None:
                return {"status": "skipped", "reason": "session_missing"}
            if turn is None:
                return {"status": "skipped", "reason": "turn_missing"}
            if turn.status != "pending":
                return {"status": "skipped", "reason": turn.status}
            if session.status in SESSION_TERMINAL_STATUSES:
                await repo.finish_turn(turn, status="cancelled", error_code="session_terminal")
                CodingSessionService(db).clear_pending_turn(session, turn.id)
                await db.commit()
                return {"status": "skipped", "reason": "session_terminal"}
            plan_only = _queued_plan_only(session, turn.id, plan_only)
            await repo.mark_turn_running(turn)
            await db.commit()
            agent_config = await _load_agent_config_for_session(db, session)
            if await coding_cancel_requested(session.id):
                await cancel_queued_turn(db, session, turn)
                return {"status": "cancelled", "session_id": session.id, "turn_seq": turn.seq}
            service = CodingExecutionService(
                db,
                uid=session.uid,
                thread_id=session.runtime_scope_id,
                runtime_scope_id=session.runtime_scope_id,
                workdir_relative_path=session.workdir_path,
                provider=provider,
                backend=backend,
            )
            error_code = "coding_prepare_failed"
            try:
                secrets = await service.prepare(agent_config)
                # ensure_ready 会锁定 AgentSandbox；执行 CLI 前必须提交，避免阻塞独立 heartbeat。
                await db.commit()
                error_code = "coding_worker_error"
                outcome = await service._execute_turn_tail(
                    session=session,
                    turn=turn,
                    executor=session.executor,
                    task=turn.request_text,
                    plan_only=plan_only,
                    secrets=secrets,
                    ownership_guard=lambda: _owns_coding_turn_lease(
                        db=db,
                        scope=scope,
                        owner_id=owner_id,
                        heartbeat_lost=heartbeat_lost,
                        lease_service=lease_service,
                    ),
                )
                return outcome.to_dict()
            except CodingTurnOwnershipLostError:
                return {"status": "skipped", "reason": "ownership_lost"}
            except Exception as exc:  # noqa: BLE001
                error_message = f"编码 turn 准备或执行失败：{type(exc).__name__}"
                failed = await _fail_owned_coding_turn(
                    db=db,
                    session_id=session_id,
                    turn_id=turn_id,
                    scope=scope,
                    owner_id=owner_id,
                    heartbeat_lost=heartbeat_lost,
                    error_code=error_code,
                    error_message=error_message,
                    lease_service=lease_service,
                )
                if not failed:
                    return {"status": "skipped", "reason": "ownership_lost"}
                return {
                    "status": "failed",
                    "session_id": session_id,
                    "error_code": error_code,
                }
    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        await lease.release(
            uid=scope.uid,
            agent_slug=scope.agent_slug or "",
            project_id=scope.project_id or "",
            owner_id=owner_id,
        )


async def _heartbeat_coding_turn_lease(*, lease, scope, owner_id: str, lost: asyncio.Event) -> None:
    """异步 turn 执行期间续租；续租失败后由终态 fencing 拒绝写入。"""
    interval = max(1, sandbox_lease_seconds() // 3)
    while True:
        await asyncio.sleep(interval)
        try:
            renewed = await lease.heartbeat(
                uid=scope.uid,
                agent_slug=scope.agent_slug or "",
                project_id=scope.project_id or "",
                owner_id=owner_id,
            )
        except Exception:  # noqa: BLE001
            lost.set()
            return
        if not renewed:
            lost.set()
            return


async def _owns_coding_turn_lease(
    *, db, scope, owner_id: str, heartbeat_lost: asyncio.Event, lease_service=None
) -> bool:
    """在终态事务中锁定并验证 turn 的沙盒租约。"""
    if heartbeat_lost.is_set():
        return False
    service = lease_service or SandboxLeaseService(db=db)
    return await service.owns_active(
        uid=scope.uid,
        agent_slug=scope.agent_slug or "",
        project_id=scope.project_id or "",
        owner_id=owner_id,
    )


async def _fail_owned_coding_turn(
    *,
    db,
    session_id: str,
    turn_id: str,
    scope,
    owner_id: str,
    heartbeat_lost: asyncio.Event,
    error_code: str,
    error_message: str,
    lease_service=None,
) -> bool:
    """仅在仍持有执行租约时把异常 turn 收敛为 failed。"""
    await db.rollback()
    if not await _owns_coding_turn_lease(
        db=db,
        scope=scope,
        owner_id=owner_id,
        heartbeat_lost=heartbeat_lost,
        lease_service=lease_service,
    ):
        return False
    repo = CodingSessionRepository(db)
    session = await repo.get_for_update(session_id)
    turn = await repo.get_turn_for_update(turn_id)
    if session is None or turn is None or turn.status != "running":
        await db.rollback()
        return False
    await repo.finish_turn(
        turn,
        status="failed",
        error_code=error_code,
        error_message=error_message,
    )
    service = CodingSessionService(db)
    service.clear_pending_turn(session, turn.id)
    await repo.append_event(
        session,
        kind="turn_finished",
        turn_id=turn.id,
        payload={"seq": turn.seq, "status": "failed", "error_code": error_code},
    )
    if session.status == "running":
        await service.transition(
            session,
            status="failed",
            error_code=error_code,
            error_message=error_message,
        )
    await db.commit()
    return True


async def cancel_queued_turn(db, session, turn) -> None:
    """执行前发现取消信号：把 pending turn 与会话一并收敛为 cancelled。"""
    repo = CodingSessionRepository(db)
    await repo.finish_turn(turn, status="cancelled", error_code="cancel_requested")
    service = CodingSessionService(db)
    service.clear_pending_turn(session, turn.id)
    await repo.append_event(
        session,
        kind="turn_finished",
        turn_id=turn.id,
        payload={"seq": turn.seq, "status": "cancelled"},
    )
    await service.transition(session, status="cancelled")
    await clear_coding_cancel_signal(session.id)
    await db.commit()


async def enqueue_coding_turn(*, session_id: str, turn_id: str, plan_only: bool = False) -> None:
    """把 pending turn 投递给 worker；投递失败由调用方显式处理。"""
    from yuxi.services.run_queue_service import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job("process_coding_turn", session_id, turn_id, plan_only)


async def reconcile_coding_turns(
    *,
    stale_seconds: int | None = None,
    session_factory=None,
    enqueue=None,
    lease_service=None,
) -> dict[str, int]:
    """补投 pending turn，并把超时 running turn 收敛为可观察失败。"""
    stale_after = int(stale_seconds or (coding_turn_timeout_seconds() + 300))
    pending: list[tuple[str, str, bool]] = []
    failed = 0
    factory = session_factory or pg_manager.get_async_session_context
    publish = enqueue or enqueue_coding_turn
    async with factory() as db:
        repo = CodingSessionRepository(db)
        for turn in await repo.list_turns_by_status(status="pending"):
            session = await repo.get(turn.session_id)
            pending.append((turn.session_id, turn.id, _queued_plan_only(session, turn.id) if session else False))
        cutoff = utc_now_naive() - timedelta(seconds=stale_after)
        for turn in await repo.list_turns_by_status(status="running", started_before=cutoff):
            session = await repo.get(turn.session_id)
            if session is None:
                continue
            scope = SandboxScope.from_runtime_scope(
                uid=str(session.uid), runtime_scope_id=str(session.runtime_scope_id)
            )
            owner_prefix = coding_turn_owner_prefix(turn.id)
            lease = lease_service or SandboxLeaseService(db=db)
            if scope.kind == "agent_project" and await lease.owns_active_prefix(
                uid=scope.uid,
                agent_slug=scope.agent_slug or "",
                project_id=scope.project_id or "",
                owner_kind="coding_session",
                owner_id_prefix=owner_prefix,
            ):
                await db.commit()
                continue
            session = await repo.get_for_update(turn.session_id)
            locked_turn = await repo.get_turn_for_update(turn.id)
            if session is None or locked_turn is None or locked_turn.status != "running":
                continue
            await repo.finish_turn(
                locked_turn,
                status="failed",
                error_code="coding_worker_lost",
                error_message="编码 turn 执行超时且 worker 未能收敛结果",
            )
            CodingSessionService(db).clear_pending_turn(session, locked_turn.id)
            await repo.append_event(
                session,
                kind="turn_finished",
                turn_id=locked_turn.id,
                payload={
                    "seq": locked_turn.seq,
                    "status": "failed",
                    "error_code": "coding_worker_lost",
                },
            )
            if session.status == "running":
                await CodingSessionService(db).transition(
                    session,
                    status="failed",
                    error_code="coding_worker_lost",
                    error_message="编码 turn 执行超时且 worker 未能收敛结果",
                )
            failed += 1
        await db.commit()
    for session_id, turn_id, plan_only in pending:
        await publish(session_id=session_id, turn_id=turn_id, plan_only=plan_only)
    return {"republished": len(pending), "failed": failed}


async def wait_for_latest_turn(
    *,
    uid: str,
    session_id: str,
    timeout_seconds: float = 300.0,
    poll_seconds: float = 2.0,
    session_factory=None,
) -> dict:
    """轮询会话直到最新 turn 进入终态；超时返回 wait_timed_out。"""
    factory = session_factory or pg_manager.get_async_session_context
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, float(timeout_seconds))
    while True:
        async with factory() as db:
            service = CodingSessionService(db)
            detail = await service.session_detail(uid=uid, session_id=session_id, event_limit=0)
        if detail is None:
            return {"status": "not_found", "session_id": session_id}
        turns = detail.get("turns") or []
        latest = turns[-1] if turns else None
        if latest is not None and latest["status"] in {"completed", "failed", "cancelled"}:
            return {
                "session_id": session_id,
                "status": detail["status"],
                "turn": latest,
            }
        if loop.time() >= deadline:
            return {
                "session_id": session_id,
                "status": "wait_timed_out",
                "session_state": detail["status"],
            }
        await asyncio.sleep(max(0.05, float(poll_seconds)))
