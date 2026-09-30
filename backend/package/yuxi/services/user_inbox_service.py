"""用户收件箱读写用例。"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.user_inbox_repository import UserInboxRepository
from yuxi.storage.postgres.models_business import User, UserInboxItem
from yuxi.utils.datetime_utils import format_utc_datetime


def _item_data(item: UserInboxItem) -> dict:
    """输出通知与来源定位信息。"""
    return {
        "id": item.id,
        "kind": item.kind,
        "source_id": item.source_id,
        "project_id": item.project_id,
        "title": item.title,
        "summary": item.summary,
        "read_at": format_utc_datetime(item.read_at),
        "archived_at": format_utc_datetime(item.archived_at),
        "created_at": format_utc_datetime(item.created_at),
    }


async def list_items(*, db: AsyncSession, user: User, folder: str, before: str | None = None) -> list[dict]:
    """读取未读、已读或归档通知。"""
    if folder not in {"unread", "read", "archived"}:
        raise HTTPException(status_code=422, detail="收件箱分类无效")
    try:
        items = await UserInboxRepository(db).list_for_user(uid=str(user.uid), folder=folder, before=before)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [_item_data(item) for item in items]


async def update_item(*, db: AsyncSession, user: User, item_id: str, read: bool | None, archived: bool | None) -> dict:
    """修改当前用户通知的阅读或归档状态。"""
    if read is None and archived is None:
        raise HTTPException(status_code=422, detail="至少指定一项状态")
    item = await UserInboxRepository(db).update_for_user(
        uid=str(user.uid), item_id=item_id, read=read, archived=archived
    )
    if item is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    await db.commit()
    return _item_data(item)
