"""编码会话执行用例：在专属沙盒内运行 headless turn 并持久化。"""

from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass

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
from yuxi.services.coding_credential_service import (
    CodingCredentialMissingError,
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
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import AgentRun

DEFAULT_CODING_TURN_TIMEOUT_SECONDS = 600


def coding_turn_timeout_seconds() -> int:
    return max(60, get_int_env("SANDBOX_CODING_TURN_TIMEOUT_SECONDS", DEFAULT_CODING_TURN_TIMEOUT_SECONDS))


class CodingScopeUnsupportedError(RuntimeError):
    """编码执行需要专属（agent-project）沙盒作用域。"""

    error_code = "coding_scope_unsupported"


class CodingBudgetExceededError(RuntimeError):
    """会话 turn 数超过预算。"""

    error_code = "budget_exceeded"


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
        prelude=(
            f"mkdir -p {quoted} && "
            f"cp -n /home/gem/.codex/config.toml {quoted}/config.toml 2>/dev/null || true"
        ),
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
        self.scope = SandboxScope.from_runtime_scope(
            uid=self.uid, runtime_scope_id=runtime_scope_id
        )
        if self.scope.kind != "agent_project":
            raise CodingScopeUnsupportedError(
                "coding execution requires a dedicated (agent-project) sandbox scope"
            )
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
        policy = await resolve_agent_sandbox_policy(
            db=self.db,
            agent_config=agent_config,
            agent_slug=self.scope.agent_slug or "",
            project_id=self.scope.project_id or "",
        )
        if not policy.is_dedicated:
            raise CodingScopeUnsupportedError(
                "agent sandbox policy is not dedicated; coding execution is unavailable"
            )
        credentials = CodingCredentialService(self.db)
        env, fingerprint = await credentials.build_coding_environment(
            uid=self.uid,
            executors=credentials.declared_executors(agent_config),
        )
        await SandboxLifecycleService(self.db, provider=self._provider).ensure_ready(
            uid=self.uid,
            agent_slug=self.scope.agent_slug or "",
            project_id=self.scope.project_id or "",
            policy=policy,
            workdir_path=self.workdir_relative_path,
            credential_fingerprint=fingerprint,
            env_overrides=env,
        )
        return [value for value in env.values() if value]

    async def prepare(self, agent_config: dict | None) -> list[str]:
        """公开的环境准备入口：异步入队前确保凭据与专属沙盒就绪。"""
        return await self._prepare(agent_config)

    async def terminate_cli_processes(self) -> None:
        """进程级取消：终止本沙盒内活跃的编码 CLI（前提是单 active turn）。"""
        command = (
            "pkill -f 'opencode run' 2>/dev/null; "
            "pkill -f 'codex exec' 2>/dev/null; true"
        )
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
    ) -> CodingTurnOutcome:
        secrets = await self._prepare(agent_config)
        repo = CodingSessionRepository(self.db)
        if session_id:
            session = await repo.get_for_update(session_id)
            if session is None or session.uid != self.uid:
                raise ValueError("coding session not found")
            if session.status != "idle":
                raise CodingSessionStateError(
                    f"coding session is not idle: {session.status}"
                )
        else:
            session = await self.sessions.create_session(
                uid=self.uid,
                project_id=self.scope.project_id or "",
                runtime_scope_id=self.scope.cache_key,
                executor=executor,
                workdir_path=self.workdir_relative_path,
                title=task.strip()[:120] or None,
                policy={"executor": executor},
                budget=budget,
            )
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

    async def _execute_turn_tail(
        self,
        *,
        session,
        turn,
        executor: str,
        task: str,
        plan_only: bool,
        secrets: list[str],
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
            response = await asyncio.to_thread(
                self.backend.execute, command, timeout=coding_turn_timeout_seconds()
            )
            raw_output = str(getattr(response, "output", "") or "")
            exit_code = int(getattr(response, "exit_code", 0) or 0)
        except Exception as exc:  # noqa: BLE001
            infra_error = f"sandbox execute failed: {exc}"

        events = adapter.parse_events(raw_output)
        if infra_error:
            events.append(NormalizedEvent("error", {"message": infra_error}))
        result = extract_turn_result(events)
        await self.sessions.record_events(session, turn_id=turn.id, events=events)

        cancelled = await coding_cancel_requested(session.id)
        failed = bool(result.error or infra_error or exit_code != 0)
        summary = CodingCredentialService.redact(result.output_text[:2000], secrets)
        if cancelled:
            await self.sessions.repo.finish_turn(
                turn, status="cancelled", result_summary=summary, usage=result.usage
            )
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
                error_message=CodingCredentialService.redact(
                    result.error or infra_error or "", secrets
                )
                or None,
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
            "events": [
                {"seq": event.seq, "kind": event.kind, "payload": event.payload_json}
                for event in events
            ],
        }

    async def list_sessions(self, *, conversation_id: int | None = None) -> list[dict]:
        repo = CodingSessionRepository(self.db)
        if conversation_id is not None:
            sessions = await repo.list_for_conversation(
                conversation_id=conversation_id, uid=self.uid
            )
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
    if not session.parent_run_id:
        return None
    from yuxi.repositories.agent_repository import AgentRepository

    run = await db.get(AgentRun, str(session.parent_run_id))
    if run is None:
        return None
    agent = await AgentRepository(db).get_by_slug(run.agent_slug)
    return agent.config_json if agent is not None else None


async def run_coding_turn_job(
    *,
    session_id: str,
    turn_id: str,
    plan_only: bool = False,
    session_factory=None,
    provider=None,
    backend=None,
) -> dict:
    """worker 后台执行已入队的 turn；重复执行与终态 turn 幂等跳过。"""
    factory = session_factory or pg_manager.get_async_session_context
    async with factory() as db:
        repo = CodingSessionRepository(db)
        session = await repo.get_for_update(session_id)
        if session is None:
            return {"status": "skipped", "reason": "session_missing"}
        turn = await repo.get_turn(turn_id)
        if turn is None:
            return {"status": "skipped", "reason": "turn_missing"}
        if turn.status != "pending":
            return {"status": "skipped", "reason": turn.status}
        if session.status in SESSION_TERMINAL_STATUSES:
            await repo.finish_turn(turn, status="cancelled", error_code="session_terminal")
            await db.commit()
            return {"status": "skipped", "reason": "session_terminal"}
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
        outcome = await service._execute_turn_tail(
            session=session,
            turn=turn,
            executor=session.executor,
            task=turn.request_text,
            plan_only=plan_only,
            secrets=[],
        )
        return outcome.to_dict()


async def cancel_queued_turn(db, session, turn) -> None:
    """执行前发现取消信号：把 pending turn 与会话一并收敛为 cancelled。"""
    repo = CodingSessionRepository(db)
    await repo.finish_turn(turn, status="cancelled", error_code="cancel_requested")
    await repo.append_event(
        session,
        kind="turn_finished",
        turn_id=turn.id,
        payload={"seq": turn.seq, "status": "cancelled"},
    )
    await CodingSessionService(db).transition(session, status="cancelled")
    await clear_coding_cancel_signal(session.id)
    await db.commit()


async def enqueue_coding_turn(*, session_id: str, turn_id: str, plan_only: bool = False) -> None:
    """把 pending turn 投递给 worker；投递失败由调用方显式处理。"""
    from yuxi.services.run_queue_service import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job("process_coding_turn", session_id, turn_id, plan_only)


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
