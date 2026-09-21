"""项目 Dashboard 页面 revision 元数据的数据访问层（yuanlei 域）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import ProjectDashboard
from yuxi.utils.datetime_utils import utc_now_naive


class ProjectDashboardRepository:
    """读写每个 Project 的页面 revision 与内容指纹。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def lock_project(self, project_id: str) -> None:
        """按 Project 取得事务级 advisory lock，串行化页面写入与收敛。"""
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"project-dashboard:{project_id}"},
        )

    async def get(self, *, project_id: str) -> ProjectDashboard | None:
        """读取页面 revision 元数据，不持有行锁。"""
        return await self.db.scalar(select(ProjectDashboard).where(ProjectDashboard.project_id == str(project_id)))

    async def get_for_update(self, *, project_id: str) -> ProjectDashboard | None:
        """锁定读取页面 revision 元数据。"""
        return await self.db.scalar(
            select(ProjectDashboard).where(ProjectDashboard.project_id == str(project_id)).with_for_update()
        )

    async def add(
        self,
        *,
        project_id: str,
        revision: int,
        content_sha256: str,
        content_size: int,
        operator: str,
        now: datetime | None = None,
    ) -> ProjectDashboard:
        """插入页面元数据并 flush，事务提交由调用方决定。"""
        timestamp = now or utc_now_naive()
        row = ProjectDashboard(
            project_id=str(project_id),
            revision=revision,
            content_sha256=content_sha256,
            content_size=content_size,
            updated_by=operator,
            updated_at=timestamp,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    def apply_revision(
        self,
        *,
        row: ProjectDashboard,
        revision: int,
        content_sha256: str,
        content_size: int,
        operator: str,
        now: datetime | None = None,
    ) -> None:
        """在已锁定的元数据行上推进 revision 与内容指纹。"""
        row.revision = revision
        row.content_sha256 = content_sha256
        row.content_size = content_size
        row.updated_by = operator
        row.updated_at = now or utc_now_naive()
