"""ProjectAgent（项目数字员工）持久化 Repository。"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import ProjectAgent
from yuxi.utils.datetime_utils import utc_now_naive


class ProjectAgentRepository:
    """读写 Project 的智能体归属与配置覆盖层。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def add(
        self,
        *,
        project_id: str,
        agent_slug: str,
        config_overrides: dict | None = None,
        created_by: str | None = None,
    ) -> ProjectAgent:
        """新增绑定并 flush，事务发布由调用方决定。"""
        binding = ProjectAgent(
            id=str(uuid.uuid4()),
            project_id=str(project_id),
            agent_slug=str(agent_slug),
            config_overrides=config_overrides or {},
            created_by=created_by,
            updated_by=created_by,
            created_at=utc_now_naive(),
            updated_at=utc_now_naive(),
        )
        self.db.add(binding)
        await self.db.flush()
        return binding

    async def list_for_project(self, project_id: str) -> list[ProjectAgent]:
        result = await self.db.execute(
            select(ProjectAgent)
            .where(ProjectAgent.project_id == str(project_id))
            .order_by(ProjectAgent.created_at.asc(), ProjectAgent.id.asc())
        )
        return list(result.scalars().all())

    async def get(self, project_id: str, agent_slug: str) -> ProjectAgent | None:
        return await self.db.scalar(
            select(ProjectAgent).where(
                ProjectAgent.project_id == str(project_id),
                ProjectAgent.agent_slug == str(agent_slug),
            )
        )

    async def get_for_update(self, project_id: str, agent_slug: str) -> ProjectAgent | None:
        return await self.db.scalar(
            select(ProjectAgent)
            .where(
                ProjectAgent.project_id == str(project_id),
                ProjectAgent.agent_slug == str(agent_slug),
            )
            .with_for_update()
        )

    async def list_agent_slugs_for_project(self, project_id: str) -> list[str]:
        result = await self.db.execute(
            select(ProjectAgent.agent_slug).where(ProjectAgent.project_id == str(project_id))
        )
        return list(result.scalars().all())

    async def list_all_agent_slugs(self) -> list[str]:
        result = await self.db.execute(select(ProjectAgent.agent_slug).distinct())
        return list(result.scalars().all())

    async def list_project_ids_for_agent(self, agent_slug: str) -> list[str]:
        result = await self.db.execute(select(ProjectAgent.project_id).where(ProjectAgent.agent_slug == str(agent_slug)))
        return list(result.scalars().all())

    async def delete_project_bindings(self, project_id: str) -> int:
        """删除某个 Project 的全部绑定，由 Project 删除事务调用。"""
        result = await self.db.execute(delete(ProjectAgent).where(ProjectAgent.project_id == str(project_id)))
        return int(result.rowcount or 0)
