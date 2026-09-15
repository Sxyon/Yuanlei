"""用户 Agent 定时任务的 PostgreSQL 访问边界。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    AgentRun,
    AgentRunRequest,
    ScheduledAgentJob,
    ScheduledAgentRun,
    User,
)
from yuxi.utils.datetime_utils import utc_now_naive


class ScheduledAgentRepository:
    """读写用户拥有的定时任务和触发记录。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_jobs(self, uid: str) -> list[ScheduledAgentJob]:
        result = await self.db.execute(
            select(ScheduledAgentJob)
            .where(ScheduledAgentJob.uid == str(uid), ScheduledAgentJob.deleted_at.is_(None))
            .order_by(ScheduledAgentJob.created_at.desc(), ScheduledAgentJob.id.desc())
        )
        return list(result.scalars().all())

    async def get_job(
        self,
        job_id: str,
        uid: str,
        *,
        lock: bool = False,
        include_deleted: bool = False,
    ) -> ScheduledAgentJob | None:
        stmt = select(ScheduledAgentJob).where(
            ScheduledAgentJob.id == job_id,
            ScheduledAgentJob.uid == str(uid),
        )
        if not include_deleted:
            stmt = stmt.where(ScheduledAgentJob.deleted_at.is_(None))
        if lock:
            stmt = stmt.with_for_update()
        return await self.db.scalar(stmt)

    async def get_job_by_creation_request(
        self,
        uid: str,
        request_id: str,
    ) -> ScheduledAgentJob | None:
        """按用户作用域读取幂等创建结果，包括已软删除任务。"""
        return await self.db.scalar(
            select(ScheduledAgentJob).where(
                ScheduledAgentJob.uid == str(uid),
                ScheduledAgentJob.creation_request_id == request_id,
            )
        )

    async def add_job(self, job: ScheduledAgentJob) -> ScheduledAgentJob:
        self.db.add(job)
        await self.db.flush()
        return job

    async def list_recent_runs(
        self,
        job_ids: list[str],
        uid: str,
        limit_per_job: int,
    ) -> list[tuple[ScheduledAgentRun, AgentRunRequest | None, AgentRun | None]]:
        """批量读取每个任务最近的触发记录及其 Request/Run。"""
        if not job_ids:
            return []
        ranked_runs = (
            select(
                ScheduledAgentRun.id.label("scheduled_run_id"),
                func.row_number()
                .over(
                    partition_by=ScheduledAgentRun.job_id,
                    order_by=(ScheduledAgentRun.scheduled_for.desc(), ScheduledAgentRun.id.desc()),
                )
                .label("position"),
            )
            .where(ScheduledAgentRun.job_id.in_(job_ids))
            .subquery()
        )
        result = await self.db.execute(
            select(ScheduledAgentRun, AgentRunRequest, AgentRun)
            .join(ranked_runs, ranked_runs.c.scheduled_run_id == ScheduledAgentRun.id)
            .join(ScheduledAgentJob, ScheduledAgentJob.id == ScheduledAgentRun.job_id)
            .outerjoin(AgentRunRequest, AgentRunRequest.request_id == ScheduledAgentRun.request_id)
            .outerjoin(AgentRun, AgentRun.id == AgentRunRequest.dispatched_run_id)
            .where(
                ScheduledAgentRun.job_id.in_(job_ids),
                ScheduledAgentJob.uid == str(uid),
                ranked_runs.c.position <= limit_per_job,
            )
            .order_by(
                ScheduledAgentRun.job_id,
                ScheduledAgentRun.scheduled_for.desc(),
                ScheduledAgentRun.id.desc(),
            )
        )
        return list(result.all())

    async def get_request_and_run(self, request_id: str) -> tuple[AgentRunRequest | None, AgentRun | None]:
        """读取触发记录对应的统一 Request/Run。"""
        row = (
            await self.db.execute(
                select(AgentRunRequest, AgentRun)
                .outerjoin(AgentRun, AgentRun.id == AgentRunRequest.dispatched_run_id)
                .where(AgentRunRequest.request_id == request_id)
            )
        ).one_or_none()
        return row if row else (None, None)

    async def claim_due_job(self, *, now: datetime) -> ScheduledAgentJob | None:
        """锁定活动用户的一个到期任务；触发事实由 service 在同一事务内创建。"""
        return await self.db.scalar(
            select(ScheduledAgentJob)
            .join(User, User.uid == ScheduledAgentJob.uid)
            .where(
                User.is_deleted == 0,
                ScheduledAgentJob.enabled.is_(True),
                ScheduledAgentJob.deleted_at.is_(None),
                ScheduledAgentJob.next_run_at <= now,
            )
            .order_by(ScheduledAgentJob.next_run_at.asc(), ScheduledAgentJob.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )

    async def has_active_run(self, job_id: str) -> bool:
        """按统一 Request/Run 事实判断任务是否已有非终态执行。"""
        run_id = await self.db.scalar(
            select(ScheduledAgentRun.id)
            .outerjoin(AgentRunRequest, AgentRunRequest.request_id == ScheduledAgentRun.request_id)
            .outerjoin(AgentRun, AgentRun.id == AgentRunRequest.dispatched_run_id)
            .where(
                ScheduledAgentRun.job_id == job_id,
                or_(
                    ScheduledAgentRun.status == "dispatching",
                    and_(
                        ScheduledAgentRun.status == "submitted",
                        or_(
                            AgentRunRequest.id.is_(None),
                            AgentRunRequest.status == "queued",
                            and_(
                                AgentRunRequest.status == "dispatched",
                                or_(
                                    AgentRun.id.is_(None),
                                    AgentRun.status.not_in({"completed", "failed", "cancelled", "interrupted"}),
                                ),
                            ),
                        ),
                    ),
                ),
            )
            .limit(1)
        )
        return run_id is not None

    async def add_run(self, run: ScheduledAgentRun) -> ScheduledAgentRun:
        """新增执行记录并 flush。"""
        self.db.add(run)
        await self.db.flush()
        return run

    async def get_run(self, run_id: str) -> ScheduledAgentRun | None:
        """按稳定 ID 读取一次触发意图。"""
        return await self.db.get(ScheduledAgentRun, run_id)

    async def list_dispatching_runs(self, *, before: datetime, limit: int = 100) -> list[ScheduledAgentRun]:
        result = await self.db.execute(
            select(ScheduledAgentRun)
            .where(
                ScheduledAgentRun.status == "dispatching",
                ScheduledAgentRun.created_at <= before,
            )
            .order_by(ScheduledAgentRun.created_at.asc(), ScheduledAgentRun.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete_job(self, job: ScheduledAgentJob) -> None:
        """软删除任务，保留执行记录。"""
        job.enabled = False
        job.deleted_at = utc_now_naive()
        job.updated_at = job.deleted_at
        await self.db.flush()
