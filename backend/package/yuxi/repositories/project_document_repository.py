"""项目命名 JSON 文档的数据访问层（yuanlei 域）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import ProjectDocument
from yuxi.utils.datetime_utils import utc_now_naive


class ProjectDocumentRepository:
    """按 (project_id, key) 读写版本化 JSON 文档。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def lock_key(self, *, project_id: str, key: str) -> None:
        """对 (project_id, key) 取得事务级 advisory lock，串行化同键写入。"""
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"project-document:{project_id}:{key}"},
        )

    async def get(self, *, project_id: str, key: str) -> ProjectDocument | None:
        """读取文档，不持有行锁。"""
        return await self.db.scalar(
            select(ProjectDocument).where(
                ProjectDocument.project_id == str(project_id),
                ProjectDocument.key == str(key),
            )
        )

    async def get_for_update(self, *, project_id: str, key: str) -> ProjectDocument | None:
        """锁定读取文档，供单次读改写使用。"""
        return await self.db.scalar(
            select(ProjectDocument)
            .where(
                ProjectDocument.project_id == str(project_id),
                ProjectDocument.key == str(key),
            )
            .with_for_update()
        )

    async def add(
        self,
        *,
        project_id: str,
        key: str,
        content: Any,
        operator: str,
        now: datetime | None = None,
    ) -> ProjectDocument:
        """插入 version 1 文档并 flush，事务提交由调用方决定。"""
        timestamp = now or utc_now_naive()
        row = ProjectDocument(
            id=str(uuid.uuid4()),
            project_id=str(project_id),
            key=str(key),
            content=content,
            version=1,
            created_by=operator,
            updated_by=operator,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    def apply_content(
        self,
        *,
        row: ProjectDocument,
        content: Any,
        operator: str,
        now: datetime | None = None,
    ) -> None:
        """在已锁定的文档上推进版本并替换内容。"""
        row.content = content
        row.version = int(row.version) + 1
        row.updated_by = operator
        row.updated_at = now or utc_now_naive()
