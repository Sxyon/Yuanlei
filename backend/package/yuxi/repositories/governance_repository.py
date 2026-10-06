"""元垒项目治理域的数据访问层：议题/决策/任务/汇报（yuanlei 域）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    GovernanceDecision,
    GovernanceDecisionRevision,
    GovernanceDecisionEvent,
    GovernanceDecisionErratum,
    Project,
    GovernanceReport,
    GovernanceTask,
    GovernanceTopic,
    GovernanceTopicComment,
    GovernanceTopicRevision,
    GovernanceTopicEvent,
    ProjectWorkTask,
    ProjectWorkResultTopicFeedback,
    ProjectWorkExecution,
    WorkSuggestionAdmission,
    ChannelDelegation,
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
        return await self.db.scalar(
            select(GovernanceTopic).where(GovernanceTopic.id == str(topic_id), GovernanceTopic.deleted_at.is_(None))
        )

    async def get_topic_for_update(self, *, topic_id: str) -> GovernanceTopic | None:
        """锁定读取议题，供单次审核读改写使用。"""
        return await self.db.scalar(
            select(GovernanceTopic)
            .where(GovernanceTopic.id == str(topic_id), GovernanceTopic.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
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

    async def list_topics(self, *, project_id: str, include_archived: bool = False) -> list[GovernanceTopic]:
        """按创建时间读取项目内议题。"""
        result = await self.db.scalars(
            select(GovernanceTopic)
            .where(
                GovernanceTopic.project_id == str(project_id),
                GovernanceTopic.deleted_at.is_(None),
                True if include_archived else GovernanceTopic.archived_at.is_(None),
            )
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
        discussion_type: str = "discussion",
        revision_number: int | None = None,
    ) -> GovernanceTopicComment:
        """插入一条议题讨论回复并 flush。"""
        row = GovernanceTopicComment(
            id=str(uuid.uuid4()),
            topic_id=str(topic_id),
            content=content,
            discussion_type=discussion_type,
            revision_number=revision_number,
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

    async def add_topic_revision(
        self, topic: GovernanceTopic, *, operator: str, author_name: str, reason: str | None
    ) -> None:
        """在拥有议题锁的事务内保存当前正文快照。"""
        self.db.add(
            GovernanceTopicRevision(
                topic_id=topic.id,
                number=topic.revision_number,
                title=topic.title,
                summary=topic.summary,
                reason=reason,
                created_by=operator,
                author_name=author_name,
                origin="authored",
            )
        )
        await self.db.flush()

    async def add_topic_event(
        self,
        topic: GovernanceTopic,
        *,
        kind: str,
        operator: str,
        author_name: str,
        reason: str | None = None,
        comment_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        """共享议题行锁分配历史序号，提交由服务负责。"""
        topic.history_sequence += 1
        self.db.add(
            GovernanceTopicEvent(
                topic_id=topic.id,
                sequence=topic.history_sequence,
                kind=kind,
                revision_number=topic.revision_number,
                comment_id=comment_id,
                created_by=operator,
                author_name=author_name,
                reason=reason,
                details=details or {},
            )
        )
        await self.db.flush()

    async def list_topic_timeline(self, topic_id: str, *, before: int | None, limit: int):
        """按稳定序号倒序分页，联结对应快照及讨论。"""
        query = (
            select(GovernanceTopicEvent, GovernanceTopicRevision, GovernanceTopicComment)
            .outerjoin(
                GovernanceTopicRevision,
                (GovernanceTopicRevision.topic_id == GovernanceTopicEvent.topic_id)
                & (GovernanceTopicRevision.number == GovernanceTopicEvent.revision_number),
            )
            .outerjoin(GovernanceTopicComment, GovernanceTopicComment.id == GovernanceTopicEvent.comment_id)
            .where(
                GovernanceTopicEvent.topic_id == topic_id,
            )
        )
        if before is not None:
            query = query.where(GovernanceTopicEvent.sequence < before)
        return (await self.db.execute(query.order_by(GovernanceTopicEvent.sequence.desc()).limit(limit))).all()

    async def topic_references(self, topic_id: str) -> list[str]:
        """检查决策和两类任务；执行依据由其不可删除的来源关系保护。"""
        references = []
        for model, label in (
            (GovernanceDecision, "关联决策"),
            (GovernanceTask, "治理任务及其执行依据"),
            (ProjectWorkTask, "正式工作及其执行依据"),
        ):
            if await self.db.scalar(select(model.id).where(model.topic_id == topic_id).limit(1)):
                references.append(label)
        if await self.db.scalar(
            select(ProjectWorkExecution.id).where(ProjectWorkExecution.source_topic_id == topic_id).limit(1)
        ):
            references.append("正式工作历史执行依据")
        if await self.db.scalar(
            select(ChannelDelegation.id).where(ChannelDelegation.source_topic_id == topic_id).limit(1)
        ):
            references.append("正式工作历史委派依据")
        if await self.db.scalar(
            select(ProjectWorkResultTopicFeedback.id)
            .where(ProjectWorkResultTopicFeedback.topic_id == topic_id)
            .limit(1)
        ):
            references.append("工作结果反馈")
        return references

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
        if decision_id is not None:
            await self.lock_decision_project(project_id)
            decision = await self.get_decision_for_update(decision_id)
            if decision is None or decision.project_id != project_id:
                raise PermissionError("决策已删除或不属于项目")
        if topic_id is not None:
            topic = await self.get_topic_for_update(topic_id=topic_id)
            if topic is None or topic.project_id != project_id or topic.archived_at is not None:
                raise PermissionError("议题已删除、归档或不属于项目")
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

    async def work_suggestions(self, work_task_id: str):
        """读取正式工作承接的全部建议与来源，保留不同建议依据。"""
        return list(
            await self.db.scalars(
                select(GovernanceTask)
                .join(WorkSuggestionAdmission, WorkSuggestionAdmission.suggestion_id == GovernanceTask.id)
                .where(WorkSuggestionAdmission.work_task_id == work_task_id)
                .order_by(WorkSuggestionAdmission.created_at.desc())
            )
        )

    async def admission(self, suggestion_id: str):
        """读取建议的唯一正式工作及稳定编号。"""
        return (
            await self.db.execute(
                select(WorkSuggestionAdmission, ProjectWorkTask)
                .join(ProjectWorkTask, ProjectWorkTask.id == WorkSuggestionAdmission.work_task_id)
                .where(WorkSuggestionAdmission.suggestion_id == suggestion_id)
            )
        ).first()

    async def add_admission(
        self, *, suggestion_id: str, work_task_id: str, project_id: str, mode: str, uid: str, reason: str | None
    ):
        """追加唯一映射，组合外键兜底同项目。"""
        row = WorkSuggestionAdmission(
            suggestion_id=suggestion_id,
            work_task_id=work_task_id,
            project_id=project_id,
            mode=mode,
            created_by=uid,
            reason=reason,
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

    async def lock_decision_project(self, project_id: str) -> None:
        """项目内决策写与引用创建共享锁，闭合跨议题事务顺序。"""
        await self.db.scalar(select(Project).where(Project.id == project_id).with_for_update())

    async def get_decision_for_update(self, decision_id: str) -> GovernanceDecision | None:
        """锁定可见决策并重新读取当前版本。"""
        return await self.db.scalar(
            select(GovernanceDecision)
            .where(GovernanceDecision.id == decision_id, GovernanceDecision.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def add_decision_revision(self, row: GovernanceDecision, *, reason: str, user) -> None:
        """保存完整决策快照，旧版本不可覆盖。"""
        snapshot = {
            key: getattr(row, key)
            for key in (
                "title",
                "conclusion",
                "rationale",
                "topic_id",
                "topic_revision_number",
                "relation_type",
                "target_decision_id",
            )
        }
        self.db.add(
            GovernanceDecisionRevision(
                decision_id=row.id,
                number=row.revision_number,
                snapshot=snapshot,
                reason=reason,
                created_by=str(user.uid),
                author_name=user.username,
                origin="authored",
            )
        )
        await self.db.flush()

    async def add_decision_event(self, row: GovernanceDecision, *, kind: str, reason: str, details: dict, user) -> None:
        """局部历史序号与状态在同一锁和事务内写入。"""
        row.history_sequence += 1
        self.db.add(
            GovernanceDecisionEvent(
                decision_id=row.id,
                sequence=row.history_sequence,
                revision_number=row.revision_number,
                kind=kind,
                reason=reason,
                details=details,
                created_by=str(user.uid),
                author_name=user.username,
            )
        )
        await self.db.flush()

    async def list_decision_events(self, decision_id: str, *, before: int | None, limit: int):
        """按递增序号倒序分页并读取对应快照。"""
        query = (
            select(GovernanceDecisionEvent, GovernanceDecisionRevision)
            .join(
                GovernanceDecisionRevision,
                (GovernanceDecisionRevision.decision_id == GovernanceDecisionEvent.decision_id)
                & (GovernanceDecisionRevision.number == GovernanceDecisionEvent.revision_number),
            )
            .where(GovernanceDecisionEvent.decision_id == decision_id)
        )
        if before is not None:
            query = query.where(GovernanceDecisionEvent.sequence < before)
        return (await self.db.execute(query.order_by(GovernanceDecisionEvent.sequence.desc()).limit(limit))).all()

    async def decision_references(self, decision_id: str) -> list[str]:
        """已有任务和其他决策的真实引用保护草案删除。"""
        refs = []
        if await self.db.scalar(select(GovernanceTask.id).where(GovernanceTask.decision_id == decision_id).limit(1)):
            refs.append("治理任务及其执行依据")
        if await self.db.scalar(
            select(GovernanceDecision.id)
            .where(
                GovernanceDecision.target_decision_id == decision_id,
            )
            .limit(1)
        ):
            refs.append("补充或替代决策")
        for model in (ProjectWorkTask, ProjectWorkExecution, ChannelDelegation):
            if await self.db.scalar(select(model.id).where(model.source_decision_id == decision_id).limit(1)):
                refs.append("正式工作及其历史执行依据")
                break
        return refs

    async def list_decision_errata(self, decision_id: str):
        """读取文字勘误，原批准文本保持独立。"""
        return list(
            await self.db.scalars(
                select(GovernanceDecisionErratum)
                .where(GovernanceDecisionErratum.decision_id == decision_id)
                .order_by(GovernanceDecisionErratum.created_at.desc(), GovernanceDecisionErratum.id)
            )
        )

    async def add_decision(
        self,
        *,
        project_id: str,
        title: str,
        conclusion: str,
        rationale: str | None,
        topic_id: str | None,
        relation_type: str = "ordinary",
        target_decision_id: str | None = None,
        operator: str,
        now: datetime | None = None,
        topic_revision_number: int | None = None,
    ) -> GovernanceDecision:
        """只插入草案，批准由显式生命周期操作完成。"""
        if topic_id is not None:
            topic = await self.get_topic_for_update(topic_id=topic_id)
            if topic is None or topic.project_id != project_id or topic.archived_at is not None:
                raise PermissionError("议题已删除、归档或不属于项目")
        timestamp = now or utc_now_naive()
        row = GovernanceDecision(
            topic_revision_number=topic_revision_number,
            id=str(uuid.uuid4()),
            project_id=str(project_id),
            topic_id=topic_id,
            title=title,
            conclusion=conclusion,
            rationale=rationale,
            status="draft",
            relation_type=relation_type,
            target_decision_id=target_decision_id,
            created_by=operator,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_decision(self, *, decision_id: str) -> GovernanceDecision | None:
        """按 id 读取决策。"""
        return await self.db.scalar(
            select(GovernanceDecision).where(
                GovernanceDecision.id == str(decision_id), GovernanceDecision.deleted_at.is_(None)
            )
        )

    async def list_decisions(self, *, project_id: str) -> list[GovernanceDecision]:
        """按创建时间读取项目内决策。"""
        result = await self.db.scalars(
            select(GovernanceDecision)
            .where(GovernanceDecision.project_id == str(project_id), GovernanceDecision.deleted_at.is_(None))
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
