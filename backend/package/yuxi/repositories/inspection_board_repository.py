"""督查板只读聚合的数据访问层：按 Project 读取执行面 Run 事实（yuanlei 域）。

只读上游 `agent_runs` 与其 `conversations` 归属，不写入、不持有 Run 状态。
"""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    AgentRun,
    Conversation,
    ProjectWorkTask,
    ProjectWorkResult,
    ProjectWorkExecution,
    ChannelDelegation,
    ProjectWorkResultTopicFeedback,
)

BLOCKED_RUN_STATUSES = ("failed", "interrupted")


class InspectionBoardRepository:
    """按 Project 读取执行面 Run 事实，供督查板只读聚合使用。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    def _run_scope(self, *, project_id: str, uid: str) -> Select:
        """限定当前用户在指定 Project 下的 Run。"""
        return (
            select(AgentRun)
            .join(Conversation, Conversation.id == AgentRun.conversation_id)
            .where(Conversation.project_id == str(project_id), AgentRun.uid == str(uid))
        )

    async def list_recent_runs(self, *, project_id: str, uid: str, limit: int) -> list[AgentRun]:
        """按创建时间倒序读取项目内最近 Run。"""
        result = await self.db.scalars(
            self._run_scope(project_id=project_id, uid=uid)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(limit)
        )
        return list(result)

    async def list_blocked_runs(self, *, project_id: str, uid: str, limit: int) -> list[AgentRun]:
        """按完成时间倒序读取项目内最近失败或中断的 Run。"""
        result = await self.db.scalars(
            self._run_scope(project_id=project_id, uid=uid)
            .where(AgentRun.status.in_(BLOCKED_RUN_STATUSES))
            .order_by(AgentRun.finished_at.desc(), AgentRun.id.desc())
            .limit(limit)
        )
        return list(result)

    async def count_runs_by_status(self, *, project_id: str, uid: str) -> dict[str, int]:
        """统计项目内 Run 各状态数量。"""
        result = await self.db.execute(
            select(AgentRun.status, func.count())
            .join(Conversation, Conversation.id == AgentRun.conversation_id)
            .where(Conversation.project_id == str(project_id), AgentRun.uid == str(uid))
            .group_by(AgentRun.status)
        )
        return {status: int(count) for status, count in result.all()}

    async def list_work_facts(self, *, project_id: str) -> list[dict]:
        """读取正式工作的当前关联，不读取描述、运行输入或资料正文。"""
        fields = [
            ProjectWorkTask.id,
            ProjectWorkTask.number,
            ProjectWorkTask.title,
            ProjectWorkTask.status,
            ProjectWorkTask.due_date,
            ProjectWorkTask.updated_at,
            ProjectWorkTask.topic_id,
            ProjectWorkTask.source_decision_id,
            ProjectWorkTask.source_decision_revision,
        ]
        rows = await self.db.execute(
            select(*fields)
            .where(ProjectWorkTask.project_id == project_id)
            .order_by(ProjectWorkTask.updated_at.desc(), ProjectWorkTask.id.desc())
        )
        return [dict(row) for row in rows.mappings()]

    async def list_result_facts(self, *, project_id: str) -> list[dict]:
        """读取结果归属和当次冻结来源，保持与工作当前来源分开。"""
        rows = await self.db.execute(
            select(
                ProjectWorkResult.id,
                ProjectWorkResult.task_id,
                ProjectWorkResult.summary,
                ProjectWorkResult.status,
                ProjectWorkResult.created_at,
                ProjectWorkResult.criteria_revision,
                ProjectWorkResult.source_execution_id,
                ProjectWorkResult.source_delegation_id,
                ProjectWorkTask.number,
                ProjectWorkTask.title,
                func.coalesce(ProjectWorkExecution.source_decision_id, ChannelDelegation.source_decision_id).label(
                    "frozen_decision_id"
                ),
                func.coalesce(
                    ProjectWorkExecution.source_decision_revision, ChannelDelegation.source_decision_revision
                ).label("frozen_decision_revision"),
            )
            .join(ProjectWorkTask, ProjectWorkTask.id == ProjectWorkResult.task_id)
            .outerjoin(ProjectWorkExecution, ProjectWorkExecution.id == ProjectWorkResult.source_execution_id)
            .outerjoin(ChannelDelegation, ChannelDelegation.id == ProjectWorkResult.source_delegation_id)
            .where(ProjectWorkResult.project_id == project_id, ProjectWorkTask.project_id == project_id)
            .order_by(ProjectWorkResult.created_at.desc(), ProjectWorkResult.id.desc())
        )
        return [dict(row) for row in rows.mappings()]

    async def list_attempt_facts(self, *, project_id: str) -> list[dict]:
        """两类执行分别读取最小终态与定位，不取得输入或快照正文。"""
        result = []
        for model, task_field, state in (
            (ProjectWorkExecution, ProjectWorkExecution.task_id, ProjectWorkExecution.status),
            (ChannelDelegation, ChannelDelegation.work_task_id, ChannelDelegation.dispatch_state),
        ):
            fields = [
                model.id,
                task_field.label("task_id"),
                state.label("status"),
                model.created_at,
                ProjectWorkTask.status.label("work_status"),
                ProjectWorkTask.title,
                ProjectWorkTask.number,
            ]
            kind = "execution" if model is ProjectWorkExecution else "delegation"
            fields += (
                [model.current_run_id, model.error_message]
                if kind == "execution"
                else [model.operation_id, model.remote_status, model.error_code]
            )
            rows = await self.db.execute(
                select(*fields)
                .join(ProjectWorkTask, ProjectWorkTask.id == task_field)
                .where(model.project_id == project_id, ProjectWorkTask.project_id == project_id)
                .order_by(model.created_at.desc(), model.id.desc())
            )
            result.extend({**dict(row), "kind": kind} for row in rows.mappings())
        return result

    async def list_feedback_facts(self, *, project_id: str) -> list[dict]:
        """读取已保存的结果反馈关系，不用文件mtime推断复盘。"""
        rows = await self.db.execute(
            select(
                ProjectWorkResultTopicFeedback.id,
                ProjectWorkResultTopicFeedback.result_id,
                ProjectWorkResultTopicFeedback.topic_id,
                ProjectWorkResultTopicFeedback.topic_revision,
                ProjectWorkResultTopicFeedback.created_at,
                ProjectWorkResult.task_id,
                ProjectWorkResult.summary,
            )
            .join(ProjectWorkResult, ProjectWorkResult.id == ProjectWorkResultTopicFeedback.result_id)
            .where(ProjectWorkResultTopicFeedback.project_id == project_id)
            .order_by(ProjectWorkResultTopicFeedback.created_at.desc(), ProjectWorkResultTopicFeedback.id.desc())
        )
        return [dict(row) for row in rows.mappings()]
