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
from yuxi.services.sandbox_lifecycle_service import (
    SandboxLifecycleService,
    resolve_agent_sandbox_policy,
)

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
                await repo.append_event(
                    session,
                    kind="resume_degraded",
                    payload={"reason": "cli_state_missing", "executor": session.executor},
                )
        turn = await self.sessions.start_turn(session, request_text=task)
        await self.db.commit()

        adapter = get_coding_adapter(executor)
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

        failed = bool(result.error or infra_error or exit_code != 0)
        summary = CodingCredentialService.redact(result.output_text[:2000], secrets)
        await self.sessions.finish_turn(
            session,
            turn,
            status="failed" if failed else "completed",
            result_summary=summary,
            usage=result.usage,
            error_code="executor_error" if failed else None,
            error_message=CodingCredentialService.redact(
                result.error or infra_error or "", secrets
            ) or None,
            cli_session_ref=result.session_ref,
        )
        await self.db.commit()
        return CodingTurnOutcome(
            session_id=session.id,
            turn_seq=turn.seq,
            status=session.status,
            executor=session.executor,
            output_text=summary,
            cli_session_ref=session.cli_session_ref,
            usage=result.usage,
            event_count=len(events),
            resume_degraded=resume_degraded,
            error_code="executor_error" if failed else None,
            error_message=result.error or infra_error,
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
