"""Agent 专属沙盒所有权、生命周期与事件的数据访问层。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import AgentSandbox, AgentSandboxEvent
from yuxi.utils.datetime_utils import utc_now_naive


class AgentSandboxRepository:
    """读写 (uid, agent, project) 的专属沙盒记录与生命周期事件。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get_for_update(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
    ) -> AgentSandbox | None:
        """按归属锁定读取，供生命周期状态迁移使用。"""
        return await self.db.scalar(
            select(AgentSandbox)
            .where(
                AgentSandbox.uid == str(uid),
                AgentSandbox.agent_slug == str(agent_slug),
                AgentSandbox.project_id == str(project_id),
            )
            .with_for_update()
        )

    async def list_all(self) -> list[AgentSandbox]:
        """列出全部专属沙盒记录，供生命周期收敛扫描。"""
        result = await self.db.execute(
            select(AgentSandbox).order_by(AgentSandbox.created_at.asc(), AgentSandbox.id.asc())
        )
        return list(result.scalars().all())

    async def add(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
        scope_key: str,
        sandbox_id: str,
        lifecycle: str,
        resume_policy: str,
        idle_timeout_seconds: int | None,
        now: datetime | None = None,
    ) -> AgentSandbox:
        """新增专属沙盒记录并 flush，事务发布由调用方决定。"""
        timestamp = now or utc_now_naive()
        row = AgentSandbox(
            id=str(uuid.uuid4()),
            uid=str(uid),
            agent_slug=str(agent_slug),
            project_id=str(project_id),
            scope_key=str(scope_key),
            sandbox_id=str(sandbox_id),
            lifecycle=str(lifecycle),
            resume_policy=str(resume_policy),
            status="active",
            idle_timeout_seconds=idle_timeout_seconds,
            last_activity_at=timestamp,
            last_keepalive_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def append_event(
        self,
        *,
        sandbox_id: str,
        kind: str,
        actor_kind: str | None = None,
        actor_id: str | None = None,
        payload: dict | None = None,
        now: datetime | None = None,
    ) -> AgentSandboxEvent:
        """追加生命周期事件并 flush。"""
        event = AgentSandboxEvent(
            id=str(uuid.uuid4()),
            sandbox_id=str(sandbox_id),
            kind=str(kind),
            actor_kind=actor_kind,
            actor_id=actor_id,
            payload_json=payload or {},
            created_at=now or utc_now_naive(),
        )
        self.db.add(event)
        await self.db.flush()
        return event
