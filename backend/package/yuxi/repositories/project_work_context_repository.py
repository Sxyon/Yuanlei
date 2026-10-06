"""当次执行资料的版本和项目归属读取边界。"""

from sqlalchemy import select

from yuxi.storage.postgres.models_business import (
    GovernanceDecision,
    GovernanceDecisionRevision,
    GovernanceTopic,
    GovernanceTopicRevision,
    ProjectWorkResult,
    User,
)


class ProjectWorkContextRepository:
    """只在已授权项目内定位资料版本，不拥有事务。"""

    def __init__(self, db, project_id):
        """复用调用方事务和已授权项目范围。"""
        self.db = db
        self.project_id = project_id

    async def user(self, uid):
        """读取当前委派操作者。"""
        return await self.db.scalar(select(User).where(User.uid == uid, User.is_deleted == 0))

    async def decision(self, decision_id, revision):
        """精确读取来源批准修订与当前状态，不替换为最新修订。"""
        row = await self.db.get(GovernanceDecision, decision_id)
        if row is None or row.project_id != self.project_id or row.deleted_at:
            return None, None
        return row, await self.db.get(GovernanceDecisionRevision, (decision_id, revision))

    async def topic(self, topic_id, revision):
        """读取项目内议题选定修订。"""
        row = await self.db.get(GovernanceTopic, topic_id)
        if row is None or row.project_id != self.project_id or row.deleted_at:
            return None, None
        return row, await self.db.get(GovernanceTopicRevision, (topic_id, revision or row.revision_number))

    async def result(self, task_id, result_id):
        """业务结果仅允许同项目同工作。"""
        return await self.db.scalar(
            select(ProjectWorkResult).where(
                ProjectWorkResult.id == result_id,
                ProjectWorkResult.task_id == task_id,
                ProjectWorkResult.project_id == self.project_id,
            )
        )
