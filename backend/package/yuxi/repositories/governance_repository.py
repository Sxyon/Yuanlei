"""元垒项目治理域的数据访问层：议题/决策/任务/汇报（yuanlei 域）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    GovernanceDecision,
    GovernanceReport,
    GovernanceTask,
    GovernanceTopic,
    GovernanceTopicComment,
)
from yuxi.utils.datetime_utils import utc_now_naive


class GovernanceRepository:
    """按 Project 读写治理事实；提交事务由调用方决定。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def add_topic(
        self,
        *,
        project_id: str,
        title: str,
        summary: str | None,
        source_channel: str,
        source_external_id: str | None,
        source_url: str | None,
        operator: str,
        now: datetime | None = None,
    ) -> GovernanceTopic:
        """插入一条 proposed 议题并 flush。"""
        timestamp = now or utc_now_naive()
        row = GovernanceTopic(
            id=str(uuid.uuid4()),
            project_id=str(project_id),
            title=title,
            summary=summary,
            status="proposed",
            source_channel=source_channel,
            source_external_id=source_external_id,
            source_url=source_url,
            created_by=operator,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_topic(self, *, topic_id: str) -> GovernanceTopic | None:
        """按 id 读取议题，不持有行锁。"""
        return await self.db.scalar(select(GovernanceTopic).where(GovernanceTopic.id == str(topic_id)))

    async def get_topic_for_update(self, *, topic_id: str) -> GovernanceTopic | None:
        """锁定读取议题，供单次审核读改写使用。"""
        return await self.db.scalar(
            select(GovernanceTopic).where(GovernanceTopic.id == str(topic_id)).with_for_update()
        )

    async def find_topic_by_source(
        self,
        *,
        project_id: str,
        source_channel: str,
        source_external_id: str,
    ) -> GovernanceTopic | None:
        """按 (project, channel, external_id) 查重。"""
        return await self.db.scalar(
            select(GovernanceTopic).where(
                GovernanceTopic.project_id == str(project_id),
                GovernanceTopic.source_channel == source_channel,
                GovernanceTopic.source_external_id == source_external_id,
            )
        )

    async def list_topics(self, *, project_id: str) -> list[GovernanceTopic]:
        """按创建时间读取项目内议题。"""
        result = await self.db.scalars(
            select(GovernanceTopic)
            .where(GovernanceTopic.project_id == str(project_id))
            .order_by(GovernanceTopic.created_at, GovernanceTopic.id)
        )
        return list(result)

    async def add_topic_comment(
        self,
        *,
        topic_id: str,
        content: str,
        author_name: str,
        operator: str,
        now: datetime | None = None,
    ) -> GovernanceTopicComment:
        """插入一条议题讨论回复并 flush。"""
        row = GovernanceTopicComment(
            id=str(uuid.uuid4()),
            topic_id=str(topic_id),
            content=content,
            author_name=author_name,
            created_by=operator,
            created_at=now or utc_now_naive(),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_topic_comments(self, *, topic_id: str) -> list[GovernanceTopicComment]:
        """按时间顺序读取议题讨论回复。"""
        result = await self.db.scalars(
            select(GovernanceTopicComment)
            .where(GovernanceTopicComment.topic_id == str(topic_id))
            .order_by(GovernanceTopicComment.created_at, GovernanceTopicComment.id)
        )
        return list(result)

    async def add_task(
        self,
        *,
        project_id: str,
        title: str,
        description: str | None,
        topic_id: str | None,
        decision_id: str | None,
        assignee_agent_slug: str | None,
        source_channel: str,
        source_external_id: str | None,
        source_url: str | None,
        operator: str,
        now: datetime | None = None,
    ) -> GovernanceTask:
        """插入一条 proposed 任务并 flush。"""
        timestamp = now or utc_now_naive()
        row = GovernanceTask(
            id=str(uuid.uuid4()),
            project_id=str(project_id),
            topic_id=topic_id,
            decision_id=decision_id,
            assignee_agent_slug=assignee_agent_slug,
            title=title,
            description=description,
            status="proposed",
            source_channel=source_channel,
            source_external_id=source_external_id,
            source_url=source_url,
            created_by=operator,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_task(self, *, task_id: str) -> GovernanceTask | None:
        """按 id 读取任务，不持有行锁。"""
        return await self.db.scalar(select(GovernanceTask).where(GovernanceTask.id == str(task_id)))

    async def get_task_for_update(self, *, task_id: str) -> GovernanceTask | None:
        """锁定读取任务，供单次审核读改写使用。"""
        return await self.db.scalar(select(GovernanceTask).where(GovernanceTask.id == str(task_id)).with_for_update())

    async def find_task_by_source(
        self,
        *,
        project_id: str,
        source_channel: str,
        source_external_id: str,
    ) -> GovernanceTask | None:
        """按 (project, channel, external_id) 查重。"""
        return await self.db.scalar(
            select(GovernanceTask).where(
                GovernanceTask.project_id == str(project_id),
                GovernanceTask.source_channel == source_channel,
                GovernanceTask.source_external_id == source_external_id,
            )
        )

    async def list_tasks(self, *, project_id: str) -> list[GovernanceTask]:
        """按创建时间读取项目内任务。"""
        result = await self.db.scalars(
            select(GovernanceTask)
            .where(GovernanceTask.project_id == str(project_id))
            .order_by(GovernanceTask.created_at, GovernanceTask.id)
        )
        return list(result)

    async def add_decision(
        self,
        *,
        project_id: str,
        title: str,
        conclusion: str,
        rationale: str | None,
        topic_id: str | None,
        decided: bool,
        operator: str,
        now: datetime | None = None,
    ) -> GovernanceDecision:
        """插入决策；decided 为真时同时记录拍板人与时间。"""
        timestamp = now or utc_now_naive()
        row = GovernanceDecision(
            id=str(uuid.uuid4()),
            project_id=str(project_id),
            topic_id=topic_id,
            title=title,
            conclusion=conclusion,
            rationale=rationale,
            status="implemented" if decided else "proposed",
            decided_by=operator if decided else None,
            decided_at=timestamp if decided else None,
            created_by=operator,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_decision(self, *, decision_id: str) -> GovernanceDecision | None:
        """按 id 读取决策。"""
        return await self.db.scalar(select(GovernanceDecision).where(GovernanceDecision.id == str(decision_id)))

    async def list_decisions(self, *, project_id: str) -> list[GovernanceDecision]:
        """按创建时间读取项目内决策。"""
        result = await self.db.scalars(
            select(GovernanceDecision)
            .where(GovernanceDecision.project_id == str(project_id))
            .order_by(GovernanceDecision.created_at, GovernanceDecision.id)
        )
        return list(result)

    async def add_report(
        self,
        *,
        project_id: str,
        title: str,
        summary: str | None,
        content: Any,
        source_run_id: str | None,
        artifact_path: str | None,
        operator: str,
        now: datetime | None = None,
    ) -> GovernanceReport:
        """插入汇报记录并 flush。"""
        timestamp = now or utc_now_naive()
        row = GovernanceReport(
            id=str(uuid.uuid4()),
            project_id=str(project_id),
            title=title,
            summary=summary,
            content=content,
            source_run_id=source_run_id,
            artifact_path=artifact_path,
            created_by=operator,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_reports(self, *, project_id: str) -> list[GovernanceReport]:
        """按创建时间读取项目内汇报。"""
        result = await self.db.scalars(
            select(GovernanceReport)
            .where(GovernanceReport.project_id == str(project_id))
            .order_by(GovernanceReport.created_at, GovernanceReport.id)
        )
        return list(result)
