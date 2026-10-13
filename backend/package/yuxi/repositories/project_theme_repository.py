"""项目主题来源、不可变版本与项目选择的PostgreSQL查询。"""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ProjectThemeRepository:
    """封装主题SQL；提交与文件发布顺序由用例拥有。"""

    def __init__(self, db: AsyncSession):
        """绑定当前用例的持久化或错误上下文。"""
        self.db = db

    async def sources(self, uid: str, project_id: str | None):
        """只列当前用户公共来源及有权活动项目的专属来源。"""
        result = await self.db.execute(
            text("""
            SELECT s.* FROM project_theme_sources s
            WHERE s.kind='builtin' OR (s.owner_uid=:uid AND
             (s.kind='personal' OR (s.project_id=:project_id AND EXISTS
              (SELECT 1 FROM projects p WHERE p.id=s.project_id AND p.uid=:uid
               AND p.status='active' AND p.selection_status='selectable'))))
            ORDER BY s.kind, s.created_at, s.id
        """),
            {"uid": uid, "project_id": project_id},
        )
        return [dict(row) for row in result.mappings()]

    async def source(self, source_id: str, uid: str, project_id: str | None, *, lock: bool = False):
        """在查询处执行来源可见性，专属来源只允许准确所属项目。"""
        result = await self.db.execute(
            text(
                """
            SELECT s.* FROM project_theme_sources s WHERE s.id=:source_id AND
            (s.kind='builtin' OR (s.owner_uid=:uid AND
             (s.kind='personal' OR (s.project_id=:project_id AND EXISTS
              (SELECT 1 FROM projects p WHERE p.id=s.project_id AND p.uid=:uid
               AND p.status='active' AND p.selection_status='selectable')))))
        """
                + (" FOR UPDATE OF s" if lock else "")
            ),
            {"source_id": source_id, "uid": uid, "project_id": project_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def create(self, source_id, kind, uid, project_id, name, description, copied_from=None):
        """登记认证归属及显式复制出处。"""
        await self.db.execute(
            text("""
            INSERT INTO project_theme_sources(id,kind,owner_uid,project_id,name,description,copied_from_version_id)
            VALUES (:id,:kind,:uid,:project,:name,:description,:copied)
        """),
            dict(
                id=source_id,
                kind=kind,
                uid=uid,
                project=project_id,
                name=name,
                description=description,
                copied=copied_from,
            ),
        )

    async def candidate(self, source_id: str, digest: str):
        """来源锁内推进候选修订，已发布行与项目绑定不变。"""
        await self.db.execute(
            text("""
            UPDATE project_theme_sources SET candidate_digest=:digest,
                candidate_revision=candidate_revision+1, updated_at=CURRENT_TIMESTAMP WHERE id=:id
        """),
            {"id": source_id, "digest": digest},
        )

    async def versions(self, source_id: str):
        """读取同来源发布历史。"""
        rows = await self.db.execute(
            text("""
            SELECT * FROM project_theme_versions WHERE source_id=:id ORDER BY created_at DESC, id
        """),
            {"id": source_id},
        )
        return [dict(row) for row in rows.mappings()]

    async def version(self, version_id: str):
        """版本查询后必须再次通过source执行授权。"""
        row = (
            (await self.db.execute(text("SELECT * FROM project_theme_versions WHERE id=:id"), {"id": version_id}))
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def publish(self, source_id, parsed, revision, uid):
        """同来源锁内登记不可变版本；调用者先检查同版本内容。"""
        version_id = str(uuid.uuid4())
        await self.db.execute(
            text("""
            INSERT INTO project_theme_versions
                (id,source_id,version,digest,size,format_version,component_abi,candidate_revision,created_by)
            VALUES (:id,:source,:version,:digest,:size,:format,:abi,:revision,:uid)
        """),
            dict(
                id=version_id,
                source=source_id,
                version=parsed.definition.theme.version,
                digest=parsed.digest,
                size=parsed.size,
                format=parsed.definition.manifest.formatVersion,
                abi=parsed.definition.manifest.componentAbi,
                revision=revision,
                uid=uid,
            ),
        )
        return await self.version(version_id)

    async def binding(self, project_id: str):
        """选择身份以Project为键，与共用Workdir无关。"""
        row = (
            (
                await self.db.execute(
                    text("SELECT * FROM project_theme_bindings WHERE project_id=:id"), {"id": project_id}
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def bind(self, project_id, version_id, files, generation, uid):
        """调用者已锁Project并核对持久generation。"""
        await self.db.execute(
            text("""
            INSERT INTO project_theme_bindings(project_id,version_id,files,generation,updated_by)
            VALUES (:project,:version,CAST(:files AS JSONB),:generation,:uid)
            ON CONFLICT(project_id) DO UPDATE SET version_id=EXCLUDED.version_id,files=EXCLUDED.files,
                generation=EXCLUDED.generation,updated_by=EXCLUDED.updated_by,updated_at=CURRENT_TIMESTAMP
        """),
            dict(project=project_id, version=version_id, files=json.dumps(files), generation=generation, uid=uid),
        )

    async def change_status(self, source_id, status, reason, uid):
        """来源状态与可追溯维护事件同事务保存。"""
        await self.db.execute(
            text("""
            UPDATE project_theme_sources SET status=:status,reason=:reason,updated_at=CURRENT_TIMESTAMP WHERE id=:id
        """),
            dict(id=source_id, status=status, reason=reason),
        )
        await self.db.execute(
            text("""
            INSERT INTO project_theme_events(id,source_id,action,reason,actor_uid)
            VALUES (:id,:source,:action,:reason,:uid)
        """),
            dict(id=str(uuid.uuid4()), source=source_id, action=status, reason=reason, uid=uid),
        )

    async def references(self, source_id):
        """对账与清理在来源锁内回读全部候选／版本引用。"""
        rows = await self.db.execute(
            text("""
            SELECT digest FROM project_theme_versions WHERE source_id=:id
            UNION SELECT candidate_digest FROM project_theme_sources WHERE id=:id AND candidate_digest IS NOT NULL
        """),
            {"id": source_id},
        )
        return set(rows.scalars())

    async def history(self, source_id):
        """维护原因及执行者历史供追溯读取。"""
        rows = await self.db.execute(
            text("""
            SELECT action,reason,actor_uid,created_at FROM project_theme_events
            WHERE source_id=:id ORDER BY created_at,id
        """),
            {"id": source_id},
        )
        return [dict(row) for row in rows.mappings()]
