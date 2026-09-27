"""用户收件箱持久化查询。"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import UserInboxItem
from yuxi.utils.datetime_utils import utc_now_naive


class UserInboxRepository:
    """以接收者身份限制通知读写。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def add_once(
        self,
        *,
        uid: str,
        kind: str,
        source_id: str,
        title: str,
        project_id: str | None = None,
        summary: str | None = None,
    ) -> UserInboxItem:
        """在来源状态事务内写入一次通知。"""
        existing = await self.db.scalar(
            select(UserInboxItem).where(
                UserInboxItem.uid == uid,
                UserInboxItem.kind == kind,
                UserInboxItem.source_id == source_id,
            )
        )
        if existing is not None:
            return existing
        item = UserInboxItem(
            id=str(uuid.uuid4()),
            uid=uid,
            kind=kind,
            source_id=source_id,
            project_id=project_id,
            title=title,
            summary=summary,
        )
        self.db.add(item)
        await self.db.flush()
        return item

    async def list_for_user(
        self, *, uid: str, folder: str, before: str | None = None, limit: int = 50
    ) -> list[UserInboxItem]:
        """按收件箱文件夹读取当前用户通知。"""
        statement = select(UserInboxItem).where(UserInboxItem.uid == uid)
        if folder == "archived":
            statement = statement.where(UserInboxItem.archived_at.is_not(None))
        elif folder == "unread":
            statement = statement.where(UserInboxItem.archived_at.is_(None), UserInboxItem.read_at.is_(None))
        elif folder == "read":
            statement = statement.where(UserInboxItem.archived_at.is_(None), UserInboxItem.read_at.is_not(None))
        else:
            raise ValueError("未知收件箱文件夹")
        if before is not None:
            anchor = await self.db.scalar(
                select(UserInboxItem).where(UserInboxItem.uid == uid, UserInboxItem.id == before)
            )
            if anchor is None:
                raise ValueError("分页游标无效")
            statement = statement.where(
                or_(
                    UserInboxItem.created_at < anchor.created_at,
                    and_(UserInboxItem.created_at == anchor.created_at, UserInboxItem.id < anchor.id),
                )
            )
        result = await self.db.execute(
            statement.order_by(UserInboxItem.created_at.desc(), UserInboxItem.id.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def update_for_user(
        self, *, uid: str, item_id: str, read: bool | None, archived: bool | None
    ) -> UserInboxItem | None:
        """只修改当前用户自己的通知阅读和归档状态。"""
        item = await self.db.scalar(
            select(UserInboxItem).where(UserInboxItem.uid == uid, UserInboxItem.id == item_id).with_for_update()
        )
        if item is None:
            return None
        now = utc_now_naive()
        if read is not None:
            item.read_at = now if read else None
        if archived is not None:
            item.archived_at = now if archived else None
        await self.db.flush()
        return item
