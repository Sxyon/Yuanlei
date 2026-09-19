"""专属沙盒管理 HTTP 表面：列表、配额用量、手动回收与重建。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services.sandbox_management_service import SandboxManagementService
from yuxi.storage.postgres.models_business import User

coding_sandboxes = APIRouter(prefix="/coding/sandboxes", tags=["coding-sandboxes"])


def _management_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=502, detail="沙盒操作失败，请查看服务日志")


@coding_sandboxes.get("")
async def list_coding_sandboxes(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户的专属沙盒、配额与用量。"""
    return await SandboxManagementService(db).list_user_sandboxes(uid=str(current_user.uid))


@coding_sandboxes.post("/{agent_slug}/{project_id}/suspend")
async def suspend_coding_sandbox(
    agent_slug: str,
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """手动回收 runtime（保留记录，不改 Workdir 字节）。"""
    try:
        return await SandboxManagementService(db).suspend(
            uid=str(current_user.uid), agent_slug=agent_slug, project_id=project_id
        )
    except Exception as exc:  # noqa: BLE001
        raise _management_error(exc) from None


@coding_sandboxes.post("/{agent_slug}/{project_id}/rebuild")
async def rebuild_coding_sandbox(
    agent_slug: str,
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """手动重建：回收旧 runtime 后按当前策略与凭据重建。"""
    try:
        return await SandboxManagementService(db).rebuild(
            uid=str(current_user.uid), agent_slug=agent_slug, project_id=project_id
        )
    except Exception as exc:  # noqa: BLE001
        raise _management_error(exc) from None
