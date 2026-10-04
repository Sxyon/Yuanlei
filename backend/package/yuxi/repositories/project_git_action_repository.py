"""Git 审批历史与关联执行身份的数据库边界。"""

from sqlalchemy import select
from yuxi.storage.postgres.models_business import ProjectGitAction, AgentRun, Conversation, Project


class ProjectGitActionRepository:
    """只读取当前用户项目的申请，稳定排序并保留历史。"""

    def __init__(self, db):
        self.db = db

    async def get(self, uid, project_id, action_id, *, lock=False):
        """按项目归属回读申请，批准时锁定。"""
        query = select(ProjectGitAction).where(
            ProjectGitAction.uid == uid, ProjectGitAction.project_id == project_id, ProjectGitAction.id == action_id
        )
        return await self.db.scalar(
            (query.with_for_update() if lock else query).execution_options(populate_existing=True)
        )

    async def by_request(self, uid, request_id):
        """恢复相同幂等申请，不创建第二次批准。"""
        return await self.db.scalar(
            select(ProjectGitAction).where(ProjectGitAction.uid == uid, ProjectGitAction.request_id == request_id)
        )

    async def list(self, uid, project_id, *, limit=50, offset=0):
        """返回倒序审批历史及稳定分页。"""
        return list(
            await self.db.scalars(
                select(ProjectGitAction)
                .where(ProjectGitAction.uid == uid, ProjectGitAction.project_id == project_id)
                .order_by(ProjectGitAction.created_at.desc(), ProjectGitAction.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    async def root_context(self, uid, run_id):
        """用实际 Run 与 Conversation 重建用户项目，不接受模型传入项目身份。"""
        return (
            await self.db.execute(
                select(AgentRun, Project)
                .join(Conversation, Conversation.id == AgentRun.conversation_id)
                .join(Project, Project.id == Conversation.project_id)
                .where(
                    AgentRun.uid == uid,
                    AgentRun.id == run_id,
                    Conversation.uid == uid,
                    Conversation.status != "deleted",
                    Project.uid == uid,
                    Project.status == "active",
                )
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
