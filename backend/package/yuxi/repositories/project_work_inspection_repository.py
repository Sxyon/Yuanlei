"""第一负责人周期巡检的 PostgreSQL 访问边界。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    Agent,
    ProjectWorkComment,
    ProjectWorkInspectionRun,
    ProjectWorkTask,
)
from yuxi.utils.datetime_utils import utc_now_naive


class ProjectWorkInspectionRepository:
    """以系统角色读写巡检计划、运行事实与巡检输出。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def claim_due_task(self, *, now: datetime) -> ProjectWorkTask | None:
        """在调用方事务中认领一个到期的任务巡检，跳过被其他 worker 锁定的行。"""
        return await self.db.scalar(
            select(ProjectWorkTask)
            .where(
                ProjectWorkTask.inspection_enabled.is_(True),
                ProjectWorkTask.inspection_next_run_at.is_not(None),
                ProjectWorkTask.inspection_next_run_at <= now,
                ProjectWorkTask.primary_owner_agent_slug.is_not(None),
                ProjectWorkTask.status.notin_(("done", "cancelled")),
            )
            .order_by(ProjectWorkTask.inspection_next_run_at.asc(), ProjectWorkTask.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )

    async def add_run(
        self, *, task: ProjectWorkTask, occurrence_key: str, created_at: datetime
    ) -> ProjectWorkInspectionRun:
        """登记一次巡检运行；同一 occurrence 唯一约束保证重复 tick 幂等。"""
        row = ProjectWorkInspectionRun(
            id=str(uuid.uuid4()),
            task_id=task.id,
            project_id=task.project_id,
            occurrence_key=occurrence_key,
            status="claimed",
            created_at=created_at,
            updated_at=created_at,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_run_for_update(self, run_id: str) -> ProjectWorkInspectionRun | None:
        """锁定待处理运行，阻止重复产出。"""
        return await self.db.scalar(
            select(ProjectWorkInspectionRun).where(ProjectWorkInspectionRun.id == run_id).with_for_update()
        )

    async def list_recoverable_runs(self, *, before: datetime, limit: int) -> list[ProjectWorkInspectionRun]:
        """读取 worker 崩溃后遗留的待处理巡检。"""
        rows = await self.db.scalars(
            select(ProjectWorkInspectionRun)
            .where(
                ProjectWorkInspectionRun.status == "claimed",
                ProjectWorkInspectionRun.created_at <= before,
            )
            .order_by(ProjectWorkInspectionRun.created_at.asc(), ProjectWorkInspectionRun.id.asc())
            .limit(limit)
        )
        return list(rows)

    async def list_runs_for_task(self, task_id: str, *, limit: int = 20) -> list[ProjectWorkInspectionRun]:
        """读取任务最近的巡检结果，供任务详情展示。"""
        rows = await self.db.scalars(
            select(ProjectWorkInspectionRun)
            .where(ProjectWorkInspectionRun.task_id == task_id)
            .order_by(ProjectWorkInspectionRun.created_at.desc(), ProjectWorkInspectionRun.id.desc())
            .limit(limit)
        )
        return list(rows)

    async def last_completed_finding(self, task_id: str) -> str | None:
        """读取上一次完成的巡检结论，用于只在异常变化时产出。"""
        return await self.db.scalar(
            select(ProjectWorkInspectionRun.finding)
            .where(
                ProjectWorkInspectionRun.task_id == task_id,
                ProjectWorkInspectionRun.status == "completed",
            )
            .order_by(ProjectWorkInspectionRun.created_at.desc(), ProjectWorkInspectionRun.id.desc())
            .limit(1)
        )

    async def get_task(self, task_id: str) -> ProjectWorkTask | None:
        """按标识读取任务，供 worker 在当前事务内复核。"""
        return await self.db.get(ProjectWorkTask, task_id)

    async def get_agent_name(self, agent_slug: str) -> str | None:
        """读取第一负责人显示名，供巡检输出署名。"""
        return await self.db.scalar(select(Agent.name).where(Agent.slug == agent_slug))

    async def append_comment(
        self, *, task_id: str, content: str, author_uid: str, author_name: str
    ) -> ProjectWorkComment:
        """以系统角色追加一条任务巡查评论。"""
        row = ProjectWorkComment(
            id=str(uuid.uuid4()),
            task_id=task_id,
            issue_id=None,
            content=content,
            author_uid=author_uid,
            author_name=author_name,
            created_at=utc_now_naive(),
        )
        self.db.add(row)
        await self.db.flush()
        return row
