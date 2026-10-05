"""项目工作任务、问题单与编号的数据访问边界。"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    GovernanceTopic,
    GovernanceDecision,
    GovernanceDecisionRevision,
    Project,
    ProjectAgent,
    ProjectTopicCode,
    ProjectWorkAttachment,
    ProjectWorkCode,
    ProjectWorkComment,
    ProjectWorkIssue,
    ProjectWorkReference,
    ProjectWorkTask,
)
from yuxi.utils.datetime_utils import utc_now_naive


class ProjectWorkRepository:
    """在调用方事务中读写项目工作对象。"""

    def __init__(self, db: AsyncSession, *, project_id: str, uid: str):
        self.db = db
        self.project_id = project_id
        self.uid = uid

    async def _require_project(self) -> None:
        """写入前在持久化边界重建项目归属。"""
        visible = await self.db.scalar(
            select(Project.id)
            .where(
                Project.id == self.project_id,
                Project.uid == self.uid,
                Project.status == "active",
                Project.selection_status == "selectable",
            )
            .with_for_update()
        )
        if visible is None:
            raise PermissionError("Project 不可见")

    def _visible_task_query(self):
        """将任务读取限制在当前用户的 active Project。"""
        return (
            select(ProjectWorkTask)
            .join(Project, Project.id == ProjectWorkTask.project_id)
            .where(
                ProjectWorkTask.project_id == self.project_id,
                Project.uid == self.uid,
                Project.status == "active",
                Project.selection_status == "selectable",
            )
        )

    async def get_project_code(self, project_id: str, *, lock: bool = False) -> ProjectWorkCode | None:
        """读取项目缩写；分配序号时锁定配置行。"""
        if project_id != self.project_id:
            return None
        query = (
            select(ProjectWorkCode)
            .join(Project, Project.id == ProjectWorkCode.project_id)
            .where(
                ProjectWorkCode.project_id == self.project_id,
                Project.uid == self.uid,
                Project.status == "active",
                Project.selection_status == "selectable",
            )
        )
        return await self.db.scalar(query.with_for_update(of=ProjectWorkCode) if lock else query)

    async def set_project_code(self, project_id: str, code: str) -> ProjectWorkCode:
        """插入项目缩写并 flush。"""
        await self._require_project()
        if project_id != self.project_id:
            raise PermissionError("Project 不可见")
        row = ProjectWorkCode(project_id=project_id, code=code, next_number=1)
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_topic_code(self, topic_id: str) -> ProjectTopicCode | None:
        """读取议题固化缩写。"""
        return await self.db.scalar(
            select(ProjectTopicCode)
            .join(GovernanceTopic, GovernanceTopic.id == ProjectTopicCode.topic_id)
            .join(Project, Project.id == ProjectTopicCode.project_id)
            .where(
                ProjectTopicCode.topic_id == topic_id,
                ProjectTopicCode.project_id == self.project_id,
                GovernanceTopic.project_id == self.project_id,
                Project.uid == self.uid,
                Project.status == "active",
                Project.selection_status == "selectable",
            )
        )

    async def list_topic_codes(self) -> dict[str, str]:
        """读取当前项目已固化的议题缩写映射。"""
        rows = await self.db.scalars(
            select(ProjectTopicCode)
            .join(Project, Project.id == ProjectTopicCode.project_id)
            .where(
                ProjectTopicCode.project_id == self.project_id,
                Project.uid == self.uid,
                Project.status == "active",
                Project.selection_status == "selectable",
            )
        )
        return {row.topic_id: row.code for row in rows}

    async def set_topic_code(self, project_id: str, topic_id: str, code: str) -> ProjectTopicCode:
        """插入议题缩写并 flush。"""
        await self._require_project()
        if project_id != self.project_id:
            raise PermissionError("Project 不可见")
        topic = await self.db.scalar(
            select(GovernanceTopic.id).where(GovernanceTopic.id == topic_id, GovernanceTopic.project_id == project_id)
        )
        if topic is None:
            raise PermissionError("议题不属于 Project")
        row = ProjectTopicCode(project_id=project_id, topic_id=topic_id, code=code)
        self.db.add(row)
        await self.db.flush()
        return row

    async def validate_source(
        self, *, topic_id: str | None, decision_id: str | None, review_confirmed: bool = False
    ) -> int | None:
        """按项目优先顺序校验新来源；返回不可覆盖的批准版本。"""
        from fastapi import HTTPException

        await self._require_project()
        decision = await self.db.get(GovernanceDecision, decision_id) if decision_id else None
        if decision_id and (decision is None or decision.project_id != self.project_id or decision.deleted_at):
            raise HTTPException(
                status_code=404, detail={"code": "source_decision_missing", "message": "来源决策不存在"}
            )
        if decision and topic_id and decision.topic_id != topic_id:
            raise HTTPException(
                status_code=422, detail={"code": "work_source_mismatch", "message": "议题须与来源决策的议题一致"}
            )
        for source_topic in dict.fromkeys([topic_id, decision.topic_id if decision else None]):
            if source_topic is None:
                continue
            topic = await self.db.scalar(
                select(GovernanceTopic)
                .where(
                    GovernanceTopic.id == source_topic,
                    GovernanceTopic.project_id == self.project_id,
                    GovernanceTopic.deleted_at.is_(None),
                    GovernanceTopic.archived_at.is_(None),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if topic is None:
                raise HTTPException(
                    status_code=404, detail={"code": "source_topic_unavailable", "message": "来源议题不存在或已归档"}
                )
        if decision is None:
            return None
        decision = await self.db.scalar(
            select(GovernanceDecision)
            .where(GovernanceDecision.id == decision_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if decision.status != "approved":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "source_decision_not_approved",
                    "message": "新来源须选择已批准决策；已替代或已撤销的历史依据保持可读",
                },
            )
        if decision.relation_type == "supplement":
            target = await self.db.get(GovernanceDecision, decision.target_decision_id, populate_existing=True)
            if target.status != "approved" and not review_confirmed:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "source_review_required",
                        "message": "补充决策原依据已变化，须明确确认已复核后关联",
                    },
                )
        return decision.revision_number

    async def source_detail(self, *, topic_id: str | None, decision_id: str | None, revision: int | None) -> dict:
        """读取当前状态与选定版本，历史依据退出候选后仍可定位。"""
        topic = await self.db.get(GovernanceTopic, topic_id) if topic_id else None
        decision = await self.db.get(GovernanceDecision, decision_id) if decision_id else None
        version = await self.db.get(GovernanceDecisionRevision, (decision_id, revision)) if decision_id else None
        target = (
            await self.db.get(GovernanceDecision, decision.target_decision_id)
            if decision and decision.target_decision_id
            else None
        )
        return {
            "topic": {
                "id": topic.id,
                "title": topic.title,
                "archived": topic.archived_at is not None,
                "admission_status": topic.status,
                "progress": topic.progress,
            }
            if topic
            else None,
            "decision": {
                "id": decision.id,
                "title": (version.snapshot if version else {}).get("title", decision.title),
                "status": decision.status,
                "revision_number": revision,
                "snapshot": version.snapshot if version else None,
                "requires_review": bool(
                    decision.relation_type == "supplement" and target and target.status != "approved"
                ),
            }
            if decision
            else None,
        }

    async def add_task(
        self,
        *,
        project_id: str,
        number: str,
        title: str,
        description: str | None,
        topic_id: str | None,
        parent_id: str | None,
        primary_owner_agent_slug: str | None,
        created_by: str,
        start_date: date | None = None,
        due_date: date | None = None,
        source_decision_id: str | None = None,
        review_confirmed: bool = False,
    ) -> ProjectWorkTask:
        """新增任务并 flush。"""
        await self._require_project()
        if project_id != self.project_id or created_by != self.uid:
            raise PermissionError("任务不属于当前用户 Project")
        source_revision = await self.validate_source(
            topic_id=topic_id, decision_id=source_decision_id, review_confirmed=review_confirmed
        )
        if parent_id is not None and await self.get_task(parent_id) is None:
            raise PermissionError("父任务不属于 Project")
        if topic_id is not None:
            topic = await self.db.scalar(
                select(GovernanceTopic.id)
                .where(
                    GovernanceTopic.id == topic_id,
                    GovernanceTopic.project_id == self.project_id,
                    GovernanceTopic.deleted_at.is_(None),
                    GovernanceTopic.archived_at.is_(None),
                )
                .with_for_update()
            )
            if topic is None:
                raise PermissionError("议题不属于 Project")
        if primary_owner_agent_slug is not None:
            binding = await self.db.scalar(
                select(ProjectAgent.id)
                .where(
                    ProjectAgent.project_id == self.project_id,
                    ProjectAgent.agent_slug == primary_owner_agent_slug,
                )
                .with_for_update()
            )
            if binding is None:
                raise PermissionError("负责人未绑定 Project")
        now = utc_now_naive()
        row = ProjectWorkTask(
            id=str(uuid.uuid4()),
            project_id=project_id,
            topic_id=topic_id,
            parent_id=parent_id,
            number=number,
            source_decision_id=source_decision_id,
            source_decision_revision=source_revision,
            title=title,
            description=description,
            status="todo",
            start_date=start_date,
            due_date=due_date,
            primary_owner_agent_slug=primary_owner_agent_slug,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_task(self, task_id: str, *, lock: bool = False) -> ProjectWorkTask | None:
        """读取任务；变更或分配问题单序号时锁定。"""
        query = self._visible_task_query().where(ProjectWorkTask.id == task_id)
        return await self.db.scalar(query.with_for_update(of=ProjectWorkTask) if lock else query)

    async def list_tasks(self, project_id: str) -> list[ProjectWorkTask]:
        """按创建时间列出项目任务。"""
        rows = await self.db.scalars(
            self._visible_task_query()
            .where(ProjectWorkTask.project_id == project_id)
            .order_by(ProjectWorkTask.created_at.desc(), ProjectWorkTask.id.desc())
        )
        return list(rows)

    async def add_issue(
        self, *, task_id: str, sequence: int, title: str, description: str | None, created_by: str
    ) -> ProjectWorkIssue:
        """新增任务下的问题单并 flush。"""
        await self._require_project()
        if await self.get_task(task_id) is None or created_by != self.uid:
            raise PermissionError("任务不属于当前用户 Project")
        now = utc_now_naive()
        row = ProjectWorkIssue(
            id=str(uuid.uuid4()),
            task_id=task_id,
            sequence=sequence,
            title=title,
            description=description,
            status="open",
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def next_issue_sequence(self, task_id: str) -> int:
        """在已锁定任务行后读取下一问题单序号。"""
        if await self.get_task(task_id) is None:
            raise PermissionError("任务不属于当前用户 Project")
        current = await self.db.scalar(
            select(func.max(ProjectWorkIssue.sequence)).where(ProjectWorkIssue.task_id == task_id)
        )
        return int(current or 0) + 1

    async def get_issue(self, issue_id: str, *, lock: bool = False) -> ProjectWorkIssue | None:
        """按标识读取问题单。"""
        query = (
            select(ProjectWorkIssue)
            .join(ProjectWorkTask, ProjectWorkTask.id == ProjectWorkIssue.task_id)
            .join(Project, Project.id == ProjectWorkTask.project_id)
            .where(
                ProjectWorkIssue.id == issue_id,
                ProjectWorkTask.project_id == self.project_id,
                Project.uid == self.uid,
                Project.status == "active",
                Project.selection_status == "selectable",
            )
        )
        return await self.db.scalar(query.with_for_update(of=ProjectWorkIssue) if lock else query)

    async def list_issues(self, task_id: str) -> list[ProjectWorkIssue]:
        """按任务内序号读取问题单。"""
        if await self.get_task(task_id) is None:
            return []
        rows = await self.db.scalars(
            select(ProjectWorkIssue).where(ProjectWorkIssue.task_id == task_id).order_by(ProjectWorkIssue.sequence)
        )
        return list(rows)

    async def add_reference(self, *, task_id: str, title: str, url: str, created_by: str) -> ProjectWorkReference:
        """为当前项目任务追加网页引用。"""
        await self._require_project()
        if created_by != self.uid or await self.get_task(task_id) is None:
            raise PermissionError("任务不属于当前用户 Project")
        row = ProjectWorkReference(
            id=str(uuid.uuid4()),
            task_id=task_id,
            title=title,
            url=url,
            created_by=created_by,
            created_at=utc_now_naive(),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_references(self, task_id: str) -> list[ProjectWorkReference]:
        """读取当前项目任务的网页引用。"""
        if await self.get_task(task_id) is None:
            return []
        rows = await self.db.scalars(
            select(ProjectWorkReference)
            .where(ProjectWorkReference.task_id == task_id)
            .order_by(ProjectWorkReference.created_at, ProjectWorkReference.id)
        )
        return list(rows)

    async def get_reference(self, reference_id: str) -> ProjectWorkReference | None:
        """按当前项目和用户归属读取网页引用。"""
        return await self.db.scalar(
            select(ProjectWorkReference)
            .join(ProjectWorkTask, ProjectWorkTask.id == ProjectWorkReference.task_id)
            .join(Project, Project.id == ProjectWorkTask.project_id)
            .where(
                ProjectWorkReference.id == reference_id,
                ProjectWorkTask.project_id == self.project_id,
                Project.uid == self.uid,
                Project.status == "active",
                Project.selection_status == "selectable",
            )
        )

    async def add_attachment(
        self,
        *,
        task_id: str,
        file_name: str,
        content_type: str | None,
        file_size: int,
        object_name: str,
        created_by: str,
    ) -> ProjectWorkAttachment:
        """为当前项目任务登记文件附件元数据。"""
        await self._require_project()
        if created_by != self.uid or await self.get_task(task_id) is None:
            raise PermissionError("任务不属于当前用户 Project")
        row = ProjectWorkAttachment(
            id=str(uuid.uuid4()),
            task_id=task_id,
            project_id=self.project_id,
            file_name=file_name,
            content_type=content_type,
            file_size=file_size,
            object_name=object_name,
            created_by=created_by,
            created_at=utc_now_naive(),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_attachments(self, task_id: str) -> list[ProjectWorkAttachment]:
        """读取当前项目任务的文件附件。"""
        if await self.get_task(task_id) is None:
            return []
        rows = await self.db.scalars(
            select(ProjectWorkAttachment)
            .where(ProjectWorkAttachment.task_id == task_id)
            .order_by(ProjectWorkAttachment.created_at, ProjectWorkAttachment.id)
        )
        return list(rows)

    async def get_attachment(self, attachment_id: str, *, lock: bool = False) -> ProjectWorkAttachment | None:
        """按当前项目和用户归属读取附件元数据。"""
        query = (
            select(ProjectWorkAttachment)
            .join(ProjectWorkTask, ProjectWorkTask.id == ProjectWorkAttachment.task_id)
            .join(Project, Project.id == ProjectWorkTask.project_id)
            .where(
                ProjectWorkAttachment.id == attachment_id,
                ProjectWorkTask.project_id == self.project_id,
                Project.uid == self.uid,
                Project.status == "active",
                Project.selection_status == "selectable",
            )
        )
        return await self.db.scalar(query.with_for_update(of=ProjectWorkAttachment) if lock else query)

    async def add_comment(
        self, *, task_id: str | None, issue_id: str | None, content: str, author_uid: str, author_name: str
    ) -> ProjectWorkComment:
        """追加一条讨论并 flush。"""
        await self._require_project()
        if (task_id is None) == (issue_id is None):
            raise ValueError("评论必须且只能绑定一个工作对象")
        if author_uid != self.uid:
            raise PermissionError("评论作者不匹配")
        if task_id is not None and await self.get_task(task_id) is None:
            raise PermissionError("任务不属于当前用户 Project")
        if issue_id is not None and await self.get_issue(issue_id) is None:
            raise PermissionError("Issue 不属于当前用户 Project")
        row = ProjectWorkComment(
            id=str(uuid.uuid4()),
            task_id=task_id,
            issue_id=issue_id,
            content=content,
            author_uid=author_uid,
            author_name=author_name,
            created_at=utc_now_naive(),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_comments(
        self, *, task_id: str | None = None, issue_id: str | None = None
    ) -> list[ProjectWorkComment]:
        """按对象读取追加式讨论。"""
        if (task_id is None) == (issue_id is None):
            raise ValueError("评论必须且只能绑定一个工作对象")
        if task_id is not None and await self.get_task(task_id) is None:
            return []
        if issue_id is not None and await self.get_issue(issue_id) is None:
            return []
        owner_filter = ProjectWorkComment.task_id == task_id if task_id else ProjectWorkComment.issue_id == issue_id
        rows = await self.db.scalars(
            select(ProjectWorkComment)
            .where(owner_filter)
            .order_by(ProjectWorkComment.created_at, ProjectWorkComment.id)
        )
        return list(rows)

    async def has_owner_tasks(self, agent_slug: str) -> bool:
        """解绑前检查该数字员工仍否承担项目任务责任。"""
        row = await self.db.scalar(
            self._visible_task_query()
            .with_only_columns(ProjectWorkTask.id)
            .where(ProjectWorkTask.primary_owner_agent_slug == agent_slug)
            .limit(1)
        )
        return row is not None
