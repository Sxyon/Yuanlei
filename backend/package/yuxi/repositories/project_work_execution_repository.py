"""项目工作任务执行队列的 PostgreSQL 访问边界。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    Project,
    ProjectAgent,
    ProjectWorkExecution,
    ProjectWorkTask,
    PROJECT_WORK_ACTIVE_STATUSES,
    PROJECT_WORK_EXECUTING_STATUSES,
)
from yuxi.utils.datetime_utils import utc_now_naive


class ProjectWorkExecutionRepository:
    """在调用方事务中读写分配、接受和执行尝试。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def task_for_thread(self, *, thread_id: str, project_id: str, uid: str):
        """按持久执行会话定位用户项目内任务，不依赖新请求来源标签。"""
        return await self.db.scalar(
            select(ProjectWorkTask)
            .join(ProjectWorkExecution, ProjectWorkExecution.task_id == ProjectWorkTask.id)
            .where(
                ProjectWorkExecution.thread_id == thread_id,
                ProjectWorkExecution.uid == uid,
                ProjectWorkTask.project_id == project_id,
            )
        )

    async def create(
        self, *, task_id: str, project_id: str, uid: str, agent_slug: str, prompt: str
    ) -> ProjectWorkExecution:
        """写入待接受分配，持久化边界复核任务与数字员工归属。"""
        project = await self.db.scalar(select(Project.id).where(
            Project.id == project_id, Project.uid == uid, Project.status == "active",
            Project.selection_status == "selectable",
        ).with_for_update())
        if project is None:
            raise PermissionError("Project 不可见")
        scope = await self.db.scalar(
            select(ProjectWorkTask)
            .join(Project, Project.id == ProjectWorkTask.project_id)
            .join(
                ProjectAgent,
                (ProjectAgent.project_id == ProjectWorkTask.project_id)
                & (ProjectAgent.agent_slug == agent_slug),
            )
            .where(
                ProjectWorkTask.id == task_id,
                ProjectWorkTask.project_id == project_id,
                Project.uid == uid,
                Project.status == "active",
                Project.selection_status == "selectable",
                ProjectWorkTask.status.notin_(("done", "cancelled")),
            ).with_for_update(of=ProjectWorkTask).execution_options(populate_existing=True)
        )
        if scope is None:
            raise PermissionError("任务或项目数字员工不可用")
        now = utc_now_naive()
        row = ProjectWorkExecution(
            id=str(uuid.uuid4()),
            task_id=task_id,
            project_id=project_id,
            uid=uid,
            agent_slug=agent_slug,
            status="pending_acceptance",
            prompt=prompt,
            source_topic_id=scope.topic_id,
            source_decision_id=scope.source_decision_id,
            source_decision_revision=scope.source_decision_revision,
            request_id=str(uuid.uuid4()),
            thread_id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_for_user(
        self, *, execution_id: str, project_id: str, uid: str, lock: bool = False
    ) -> ProjectWorkExecution | None:
        """按项目 Owner 限定执行尝试可见性。"""
        query = (
            select(ProjectWorkExecution)
            .join(Project, Project.id == ProjectWorkExecution.project_id)
            .where(
                ProjectWorkExecution.id == execution_id,
                ProjectWorkExecution.project_id == project_id,
                Project.uid == uid,
                Project.status == "active",
                Project.selection_status == "selectable",
            )
        )
        return await self.db.scalar(query.with_for_update(of=ProjectWorkExecution) if lock else query)

    async def list_for_task(self, *, task_id: str, project_id: str, uid: str) -> list[ProjectWorkExecution]:
        """读取当前项目任务的历次执行尝试。"""
        rows = await self.db.scalars(
            select(ProjectWorkExecution)
            .join(Project, Project.id == ProjectWorkExecution.project_id)
            .where(
                ProjectWorkExecution.task_id == task_id,
                ProjectWorkExecution.project_id == project_id,
                Project.uid == uid,
                Project.status == "active",
                Project.selection_status == "selectable",
            )
            .order_by(ProjectWorkExecution.created_at.desc(), ProjectWorkExecution.id.desc())
        )
        return list(rows)

    async def list_for_agent(
        self, *, project_id: str, uid: str, agent_slug: str
    ) -> list[ProjectWorkExecution]:
        """读取工作台所需的当前、排队与最近记录。"""
        rows = await self.db.scalars(
            select(ProjectWorkExecution)
            .join(Project, Project.id == ProjectWorkExecution.project_id)
            .where(
                ProjectWorkExecution.project_id == project_id,
                Project.uid == uid,
                Project.status == "active",
                Project.selection_status == "selectable",
                ProjectWorkExecution.agent_slug == agent_slug,
            )
            .order_by(ProjectWorkExecution.created_at.desc(), ProjectWorkExecution.id.desc())
        )
        return list(rows)

    async def has_active_agent_work(self, *, project_id: str | None, agent_slug: str) -> bool:
        """阻止解绑或删除仍有活跃任务的智能体。"""
        query = select(ProjectWorkExecution.id).where(
            ProjectWorkExecution.agent_slug == agent_slug,
            ProjectWorkExecution.status.in_(PROJECT_WORK_ACTIVE_STATUSES),
        )
        if project_id is not None:
            query = query.where(ProjectWorkExecution.project_id == project_id)
        return await self.db.scalar(query.limit(1)) is not None

    async def has_active_task_work(self, task_id: str) -> bool:
        """检查任务是否仍有待接受、排队或运行的尝试。"""
        return await self.db.scalar(
            select(ProjectWorkExecution.id)
            .where(ProjectWorkExecution.task_id == task_id, ProjectWorkExecution.status.in_(PROJECT_WORK_ACTIVE_STATUSES))
            .limit(1)
        ) is not None

    async def list_agent_slugs_to_dispatch(self, *, limit: int = 100) -> list[str]:
        """找出有可派发队头的智能体。"""
        rows = await self.db.scalars(
            select(ProjectWorkExecution.agent_slug)
            .where(ProjectWorkExecution.status == "queued")
            .distinct()
            .limit(limit)
        )
        return list(rows)

    async def claim_agent_head(self, agent_slug: str) -> ProjectWorkExecution | None:
        """按 Agent 串行认领最早待执行任务。"""
        locked = await self.db.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"project-work-agent:{agent_slug}"},
        )
        if not locked:
            return None
        active = await self.db.scalar(
            select(ProjectWorkExecution.id)
            .where(
                ProjectWorkExecution.agent_slug == agent_slug,
                ProjectWorkExecution.status.in_(PROJECT_WORK_EXECUTING_STATUSES),
            )
            .limit(1)
        )
        if active is not None:
            return None
        return await self.db.scalar(
            select(ProjectWorkExecution)
            .where(ProjectWorkExecution.agent_slug == agent_slug, ProjectWorkExecution.status == "queued")
            .order_by(ProjectWorkExecution.created_at.asc(), ProjectWorkExecution.id.asc())
            .with_for_update()
            .limit(1)
        )

    async def list_reconcilable(self, *, before: datetime, limit: int = 100) -> list[ProjectWorkExecution]:
        """读取失联派发及需要收敛的 Run 关联。"""
        rows = await self.db.scalars(
            select(ProjectWorkExecution)
            .where(
                (ProjectWorkExecution.status.in_(("submitted", "interrupted")))
                | ((ProjectWorkExecution.status == "dispatching") & (ProjectWorkExecution.updated_at <= before))
            )
            .order_by(ProjectWorkExecution.updated_at.asc(), ProjectWorkExecution.id.asc())
            .limit(limit)
        )
        return list(rows)
