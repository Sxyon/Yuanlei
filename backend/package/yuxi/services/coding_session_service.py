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

    async def list_sessions_for_uid(
        self,
        *,
        uid: str,
        conversation_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """按用户（或 Conversation）列出会话摘要。"""
        if conversation_id is not None:
            sessions = await self.repo.list_for_conversation(conversation_id=int(conversation_id), uid=str(uid))
        else:
            sessions = await self.repo.list_for_uid(uid=str(uid), limit=limit)
        return [_session_summary(session) for session in sessions]

    async def session_detail(
        self,
        *,
        uid: str,
        session_id: str,
        after_seq: int = 0,
        event_limit: int = 100,
    ) -> dict | None:
        """读取单个会话详情（含 turn 时间线与增量事件）；越权返回 None。"""
        session = await self.repo.get(session_id)
        if session is None or session.uid != str(uid):
            return None
        turns = await self.repo.list_turns(session_id=session.id)
        events = await self.repo.list_events(session_id=session.id, after_seq=after_seq, limit=event_limit)
        detail = _session_summary(session)
        detail["turns"] = [
            {
                "seq": turn.seq,
                "status": turn.status,
                "summary": turn.result_summary,
                "usage": turn.usage_json or {},
                "started_at": turn.started_at.isoformat() if turn.started_at else None,
                "ended_at": turn.ended_at.isoformat() if turn.ended_at else None,
                "error_code": turn.error_code,
            }
            for turn in turns
        ]
        detail["events"] = [
            {
                "seq": event.seq,
                "turn_id": event.turn_id,
                "kind": event.kind,
                "payload": event.payload_json,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ]
        return detail

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
            raise CodingSessionStateError(f"illegal coding session transition: {session.status} -> {target}")
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
            raise CodingSessionStateError(f"coding session is not ready for a new turn: {session.status}")
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

    async def queue_turn(
        self,
        session: CodingSession,
        *,
        request_text: str,
        plan_only: bool = False,
        enqueueing_run_id: str | None = None,
    ) -> CodingSessionTurn:
        """异步模式：会话进入 running 并创建一个 pending turn 等待 worker 执行。"""
        if session.status not in {"pending", "idle"}:
            raise CodingSessionStateError(f"coding session is not ready for a new turn: {session.status}")
        if session.status == "pending":
            await self.transition(session, status="starting")
            await self.transition(session, status="idle")
        await self.transition(session, status="running")
        turn = await self.repo.add_turn(session, request_text=request_text, status="pending")
        policy = dict(session.policy_json or {})
        policy["pending_turn"] = {
            "id": turn.id,
            "plan_only": bool(plan_only),
            "enqueueing_run_id": str(enqueueing_run_id) if enqueueing_run_id else None,
        }
        session.policy_json = policy
        await self.repo.append_event(
            session,
            kind="turn_queued",
            turn_id=turn.id,
            payload={"seq": turn.seq, "plan_only": bool(plan_only)},
        )
        return turn

    def clear_pending_turn(self, session: CodingSession, turn_id: str) -> None:
        """清除与指定 turn 匹配的待执行策略快照。"""
        policy = dict(session.policy_json or {})
        marker = policy.get("pending_turn")
        if isinstance(marker, dict) and marker.get("id") == str(turn_id):
            policy.pop("pending_turn", None)
            session.policy_json = policy

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
        self.clear_pending_turn(session, turn.id)
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


def _session_summary(session: CodingSession) -> dict:
    """会话行的对外摘要（不含凭据或原生 CLI 状态细节）。"""
    return {
        "id": session.id,
        "project_id": session.project_id,
        "conversation_id": session.conversation_id,
        "executor": session.executor,
        "mode": session.mode,
        "status": session.status,
        "title": session.title,
        "runtime_scope_id": session.runtime_scope_id,
        "terminal_attached": bool((session.policy_json or {}).get("terminal_attached")),
        "cli_session_ref": session.cli_session_ref,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "last_activity_at": session.last_activity_at.isoformat() if session.last_activity_at else None,
        "terminal_at": session.terminal_at.isoformat() if session.terminal_at else None,
        "error_code": session.error_code,
        "error_message": session.error_message,
    }
