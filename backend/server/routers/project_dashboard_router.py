"""项目 Dashboard 页面的 HTTP 读适配层（yuanlei 域扩展）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services.project_dashboard_service import get_project_dashboard_view
from yuxi.storage.postgres.models_business import User

project_dashboard = APIRouter(prefix="/projects/{project_id}/dashboard", tags=["project-dashboard"])


@project_dashboard.get("")
async def get_project_dashboard(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取项目 Dashboard 页面状态；不可见项目返回 404。"""
    return await get_project_dashboard_view(project_id=project_id, db=db, user=current_user)
