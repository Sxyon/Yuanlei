"""Run → 执行 scope 映射的数据访问层（yuanlei 域）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import AgentRunScope
from yuxi.utils.datetime_utils import utc_now_naive


class AgentRunScopeRepository:
    """读写 Run 的执行 scope key。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get(self, run_id: str) -> AgentRunScope | None:
        return await self.db.scalar(
            select(AgentRunScope).where(AgentRunScope.run_id == str(run_id))
        )

    async def upsert(self, *, run_id: str, scope_key: str) -> AgentRunScope:
        row = await self.get(run_id)
        if row is None:
            row = AgentRunScope(
                run_id=str(run_id),
                scope_key=str(scope_key),
                created_at=utc_now_naive(),
            )
            self.db.add(row)
        else:
            row.scope_key = str(scope_key)
        await self.db.flush()
        return row

    async def list_run_ids(self, *, scope_key: str) -> list[str]:
        result = await self.db.execute(
            select(AgentRunScope.run_id).where(AgentRunScope.scope_key == str(scope_key))
        )
        return [str(item) for item in result.scalars().all()]
