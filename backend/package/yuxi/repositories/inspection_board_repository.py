"""督查板只读聚合的数据访问层：按 Project 读取执行面 Run 事实（yuanlei 域）。

只读上游 `agent_runs` 与其 `conversations` 归属，不写入、不持有 Run 状态。
"""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import AgentRun, Conversation

BLOCKED_RUN_STATUSES = ("failed", "interrupted")


class InspectionBoardRepository:
    """按 Project 读取执行面 Run 事实，供督查板只读聚合使用。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    def _run_scope(self, *, project_id: str, uid: str) -> Select:
        """限定当前用户在指定 Project 下的 Run。"""
        return (
            select(AgentRun)
            .join(Conversation, Conversation.id == AgentRun.conversation_id)
            .where(Conversation.project_id == str(project_id), AgentRun.uid == str(uid))
        )

    async def list_recent_runs(self, *, project_id: str, uid: str, limit: int) -> list[AgentRun]:
        """按创建时间倒序读取项目内最近 Run。"""
        result = await self.db.scalars(
            self._run_scope(project_id=project_id, uid=uid)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(limit)
        )
        return list(result)

    async def list_blocked_runs(self, *, project_id: str, uid: str, limit: int) -> list[AgentRun]:
        """按完成时间倒序读取项目内最近失败或中断的 Run。"""
        result = await self.db.scalars(
            self._run_scope(project_id=project_id, uid=uid)
            .where(AgentRun.status.in_(BLOCKED_RUN_STATUSES))
            .order_by(AgentRun.finished_at.desc(), AgentRun.id.desc())
            .limit(limit)
        )
        return list(result)

    async def count_runs_by_status(self, *, project_id: str, uid: str) -> dict[str, int]:
        """统计项目内 Run 各状态数量。"""
        result = await self.db.execute(
            select(AgentRun.status, func.count())
            .join(Conversation, Conversation.id == AgentRun.conversation_id)
            .where(Conversation.project_id == str(project_id), AgentRun.uid == str(uid))
            .group_by(AgentRun.status)
        )
        return {status: int(count) for status, count in result.all()}
