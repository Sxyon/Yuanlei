"""当前用户收件箱 HTTP 入口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services import user_inbox_service
from yuxi.storage.postgres.models_business import User

user_inbox = APIRouter(prefix="/inbox", tags=["user-inbox"])


class InboxItemUpdate(BaseModel):
    """通知的阅读与归档变更。"""

    model_config = ConfigDict(extra="forbid")
    read: bool | None = None
    archived: bool | None = None


@user_inbox.get("")
async def list_inbox_items(
    folder: str = "unread",
    before: str | None = None,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户的通知。"""
    return await user_inbox_service.list_items(db=db, user=user, folder=folder, before=before)


@user_inbox.patch("/{item_id}")
async def update_inbox_item(
    item_id: str,
    payload: InboxItemUpdate,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """标记已读或归档。"""
    return await user_inbox_service.update_item(db=db, user=user, item_id=item_id, **payload.model_dump())
