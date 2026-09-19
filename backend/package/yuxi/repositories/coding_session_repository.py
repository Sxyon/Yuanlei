"""编码会话、turn 与归一事件的数据访问层。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    CodingSession,
    CodingSessionEvent,
    CodingSessionTurn,
)
from yuxi.utils.datetime_utils import utc_now_naive


class CodingSessionRepository:
    """读写编码会话及其 turn/事件；seq 在会话行锁内递增。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def add_session(
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
        now: datetime | None = None,
    ) -> CodingSession:
        timestamp = now or utc_now_naive()
        session = CodingSession(
            id=str(uuid.uuid4()),
            uid=str(uid),
            project_id=str(project_id),
            conversation_id=conversation_id,
            parent_run_id=parent_run_id,
            runtime_scope_id=str(runtime_scope_id),
            executor=str(executor),
            mode=str(mode),
            status="pending",
            title=title,
            workdir_path=str(workdir_path),
            policy_json=policy or {},
            budget_json=budget or {},
            last_activity_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def get(self, session_id: str) -> CodingSession | None:
        return await self.db.scalar(
            select(CodingSession).where(CodingSession.id == str(session_id))
        )

    async def get_for_update(self, session_id: str) -> CodingSession | None:
        return await self.db.scalar(
            select(CodingSession)
            .where(CodingSession.id == str(session_id))
            .with_for_update()
        )

    async def list_for_conversation(
        self, *, conversation_id: int, uid: str
    ) -> list[CodingSession]:
        result = await self.db.execute(
            select(CodingSession)
            .where(
                CodingSession.conversation_id == int(conversation_id),
                CodingSession.uid == str(uid),
            )
            .order_by(CodingSession.created_at.asc(), CodingSession.id.asc())
        )
        return list(result.scalars().all())

    async def add_turn(
        self,
        session: CodingSession,
        *,
        request_text: str,
        status: str = "running",
        now: datetime | None = None,
    ) -> CodingSessionTurn:
        timestamp = now or utc_now_naive()
        next_seq = await self._next_seq(CodingSessionTurn, session.id)
        turn = CodingSessionTurn(
            id=str(uuid.uuid4()),
            session_id=session.id,
            seq=next_seq,
            request_text=str(request_text),
            status=str(status),
            usage_json={},
            started_at=timestamp if status == "running" else None,
            created_at=timestamp,
        )
        self.db.add(turn)
        await self.db.flush()
        return turn

    async def finish_turn(
        self,
        turn: CodingSessionTurn,
        *,
        status: str,
        result_summary: str | None = None,
        usage: dict | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> CodingSessionTurn:
        timestamp = now or utc_now_naive()
        turn.status = str(status)
        turn.result_summary = result_summary
        turn.usage_json = usage or {}
        turn.error_code = error_code
        turn.error_message = error_message
        turn.ended_at = timestamp
        await self.db.flush()
        return turn

    async def append_event(
        self,
        session: CodingSession,
        *,
        kind: str,
        payload: dict | None = None,
        turn_id: str | None = None,
        now: datetime | None = None,
    ) -> CodingSessionEvent:
        timestamp = now or utc_now_naive()
        next_seq = await self._next_seq(CodingSessionEvent, session.id)
        event = CodingSessionEvent(
            id=str(uuid.uuid4()),
            session_id=session.id,
            turn_id=turn_id,
            seq=next_seq,
            kind=str(kind),
            payload_json=payload or {},
            created_at=timestamp,
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def list_events(
        self, *, session_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[CodingSessionEvent]:
        result = await self.db.execute(
            select(CodingSessionEvent)
            .where(
                CodingSessionEvent.session_id == str(session_id),
                CodingSessionEvent.seq > int(after_seq),
            )
            .order_by(CodingSessionEvent.seq.asc())
            .limit(int(limit))
        )
        return list(result.scalars().all())

    async def get_turn(self, turn_id: str) -> CodingSessionTurn | None:
        return await self.db.scalar(
            select(CodingSessionTurn).where(CodingSessionTurn.id == str(turn_id))
        )

    async def latest_turn(self, *, session_id: str) -> CodingSessionTurn | None:
        return await self.db.scalar(
            select(CodingSessionTurn)
            .where(CodingSessionTurn.session_id == str(session_id))
            .order_by(CodingSessionTurn.seq.desc())
            .limit(1)
        )

    async def mark_turn_running(
        self, turn: CodingSessionTurn, *, now: datetime | None = None
    ) -> CodingSessionTurn:
        """把已入队 turn 标记为运行中（仅 pending 生效）。"""
        if turn.status == "pending":
            turn.status = "running"
            turn.started_at = now or utc_now_naive()
            await self.db.flush()
        return turn

    async def list_turns(self, *, session_id: str) -> list[CodingSessionTurn]:
        result = await self.db.execute(
            select(CodingSessionTurn)
            .where(CodingSessionTurn.session_id == str(session_id))
            .order_by(CodingSessionTurn.seq.asc())
        )
        return list(result.scalars().all())

    async def list_for_uid(self, *, uid: str, limit: int = 50) -> list[CodingSession]:
        result = await self.db.execute(
            select(CodingSession)
            .where(CodingSession.uid == str(uid))
            .order_by(CodingSession.created_at.desc(), CodingSession.id.desc())
            .limit(int(limit))
        )
        return list(result.scalars().all())

    async def _next_seq(self, model, session_id: str) -> int:
        current = await self.db.scalar(
            select(func.max(model.seq)).where(model.session_id == session_id)
        )
        return int(current or 0) + 1
