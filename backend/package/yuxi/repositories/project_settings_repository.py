"""项目设置、负责人候选与知识库弱关联持久化。"""

from sqlalchemy import delete, select

from yuxi.permissions import ResourcePermission, resolve_knowledge_base_permission
from yuxi.storage.postgres.models_business import Agent, ProjectAgent, ProjectKnowledgeLink, ProjectSettings, User
from yuxi.storage.postgres.models_knowledge import KnowledgeBase
from yuxi.storage.minio.client import normalize_public_minio_url


class ProjectSettingsRepository:
    """复用调用方事务读写设置，所有权由 ProjectRepository 校验。"""

    def __init__(self, db):
        self.db = db

    async def get(self, project_id: str) -> ProjectSettings | None:
        """读取项目管理属性。"""
        return await self.db.get(ProjectSettings, project_id)

    async def list_for_projects(self, project_ids: list[str]) -> dict[str, ProjectSettings]:
        """批量读取已通过可见性校验的项目设置。"""
        rows = await self.db.scalars(select(ProjectSettings).where(ProjectSettings.project_id.in_(project_ids)))
        return {row.project_id: row for row in rows}

    async def members(self) -> list[dict]:
        """仅公开负责人选择所需的成员身份，不返回账号敏感字段。"""
        rows = await self.db.execute(
            select(User.uid, User.username, User.avatar).where(User.is_deleted == 0).order_by(User.username, User.uid)
        )
        return [{"id": uid, "name": name, "avatar": normalize_public_minio_url(avatar)} for uid, name, avatar in rows]

    async def agents(self, project_id: str) -> list[dict]:
        """列出当前项目已绑定智能体。"""
        rows = await self.db.execute(
            select(Agent.slug, Agent.name, Agent.icon)
            .join(ProjectAgent, ProjectAgent.agent_slug == Agent.slug)
            .where(ProjectAgent.project_id == project_id)
            .order_by(Agent.name, Agent.slug)
        )
        return [{"id": slug, "name": name, "icon": normalize_public_minio_url(icon)} for slug, name, icon in rows]

    async def knowledge(self, user) -> tuple[list[dict], set[str]]:
        """按知识库当前权限产生候选，关联不参与授权判断。"""
        rows = (await self.db.scalars(select(KnowledgeBase).order_by(KnowledgeBase.name, KnowledgeBase.kb_id))).all()
        visible = [
            {"kb_id": row.kb_id, "name": row.name}
            for row in rows
            if resolve_knowledge_base_permission(user, row) != ResourcePermission.NONE
        ]
        return visible, {row["kb_id"] for row in visible}

    async def linked_ids(self, project_id: str) -> list[str]:
        """读取关联身份，包括当前已失去读取权限的关联。"""
        return list(
            (
                await self.db.scalars(
                    select(ProjectKnowledgeLink.kb_id)
                    .where(ProjectKnowledgeLink.project_id == project_id)
                    .order_by(ProjectKnowledgeLink.kb_id)
                )
            ).all()
        )

    async def replace_links(self, project_id: str, kb_ids: list[str]) -> None:
        """在项目行锁所属事务中替换关联，不修改知识库。"""
        await self.db.execute(delete(ProjectKnowledgeLink).where(ProjectKnowledgeLink.project_id == project_id))
        self.db.add_all([ProjectKnowledgeLink(project_id=project_id, kb_id=kb_id) for kb_id in kb_ids])
