"""编码会话状态机与 turn/事件 Owner。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.coding.adapters import NormalizedEvent
from yuxi.repositories.coding_session_repository import CodingSessionRepository
from yuxi.storage.postgres.models_business import CodingSession, CodingSessionTurn
from yuxi.utils.datetime_utils import utc_now_naive

SESSION_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"starting", "cancelled", "failed"}),
    "starting": frozenset({"idle", "failed", "cancelled"}),
    "idle": frozenset({"running", "suspended", "completed", "failed", "cancelled"}),
    "running": frozenset({"idle", "awaiting_plan_approval", "suspended", "failed", "cancelled"}),
    "awaiting_plan_approval": frozenset({"running", "idle", "cancelled", "failed"}),
    "suspended": frozenset({"starting", "idle", "failed", "cancelled"}),
    "failed": frozenset(),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


class CodingSessionStateError(ValueError):
    """非法的会话状态迁移。"""


class CodingSessionService:
    """编码会话的创建、状态迁移与 turn 生命周期；提交由调用方决定。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CodingSessionRepository(db)

    async def create_session(
        self,
        *,
        uid: str,
        project_id: str,
        runtime_scope_id: str,
        executor: str,
        workdir_path: str,
        conversation_id: int | None = None,
        parent_run_id: str | None = None,
        mode: str = "headless",
        title: str | None = None,
        policy: dict | None = None,
        budget: dict | None = None,
    ) -> CodingSession:
        session = await self.repo.add_session(
            uid=uid,
            project_id=project_id,
            runtime_scope_id=runtime_scope_id,
            executor=executor,
            workdir_path=workdir_path,
            conversation_id=conversation_id,
            parent_run_id=parent_run_id,
            mode=mode,
            title=title,
            policy=policy,
            budget=budget,
        )
        await self.repo.append_event(
            session,
            kind="session_status",
            payload={"status": session.status},
        )
        return session

    async def transition(
        self,
        session: CodingSession,
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> CodingSession:
        """校验并迁移会话状态，追加 session_status 事件。"""
        target = str(status)
        allowed = _ALLOWED_TRANSITIONS.get(session.status)
        if allowed is None or target not in allowed:
            raise CodingSessionStateError(
                f"illegal coding session transition: {session.status} -> {target}"
            )
        now = utc_now_naive()
        session.status = target
        session.updated_at = now
        session.last_activity_at = now
        if target == "suspended":
            session.suspended_at = now
        if target in SESSION_TERMINAL_STATUSES:
            session.terminal_at = now
        if error_code is not None:
            session.error_code = error_code
        if error_message is not None:
            session.error_message = error_message
        await self.repo.append_event(
            session,
            kind="session_status",
            payload={"status": target, "error_code": error_code},
        )
        return session

    async def start_turn(
        self,
        session: CodingSession,
        *,
        request_text: str,
    ) -> CodingSessionTurn:
        """开启一轮：会话进入 running，创建 turn 与 turn_started 事件。"""
        if session.status not in {"pending", "idle"}:
            raise CodingSessionStateError(
                f"coding session is not ready for a new turn: {session.status}"
            )
        if session.status == "pending":
            await self.transition(session, status="starting")
            await self.transition(session, status="idle")
        await self.transition(session, status="running")
        turn = await self.repo.add_turn(session, request_text=request_text)
        await self.repo.append_event(
            session,
            kind="turn_started",
            turn_id=turn.id,
            payload={"seq": turn.seq, "request_text": request_text},
        )
        return turn

    async def finish_turn(
        self,
        session: CodingSession,
        turn: CodingSessionTurn,
        *,
        status: str,
        result_summary: str | None = None,
        usage: dict | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        cli_session_ref: str | None = None,
    ) -> CodingSessionTurn:
        """结束一轮：写 turn 终态并按结果收敛会话状态。"""
        await self.repo.finish_turn(
            turn,
            status=status,
            result_summary=result_summary,
            usage=usage,
            error_code=error_code,
            error_message=error_message,
        )
        if cli_session_ref:
            session.cli_session_ref = cli_session_ref
        await self.repo.append_event(
            session,
            kind="turn_finished",
            turn_id=turn.id,
            payload={
                "seq": turn.seq,
                "status": status,
                "summary": result_summary,
                "usage": usage or {},
                "error_code": error_code,
            },
        )
        next_status = "idle" if status == "completed" else "failed"
        await self.transition(
            session,
            status=next_status,
            error_code=error_code,
            error_message=error_message,
        )
        return turn

    async def record_events(
        self,
        session: CodingSession,
        *,
        turn_id: str | None,
        events: list[NormalizedEvent],
    ) -> None:
        """把适配器归一事件持久化到会话事件流。"""
        for event in events:
            await self.repo.append_event(
                session,
                kind=event.kind,
                turn_id=turn_id,
                payload=event.payload,
            )
