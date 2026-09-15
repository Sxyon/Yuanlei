"""Project HTTP 适配层。"""

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services.project_service import (
    create_project_view,
    delete_project_view,
    list_history_candidates_view,
    list_projects_view,
    rename_project_view,
)
from yuxi.services.project_git_service import (
    cleanup_project_worktree_view,
    create_project_repository_view,
    deactivate_project_repository_view,
    list_project_repositories_view,
    list_project_worktrees_view,
    retry_project_repository_view,
)
from yuxi.services.run_queue_service import (
    enqueue_project_git_operation,
    enqueue_project_git_worktree_cleanup,
)
from yuxi.storage.postgres.models_business import User

projects = APIRouter(prefix="/projects", tags=["projects"])


class ProjectWorkdirCreate(BaseModel):
    """Project Workdir 创建意图。"""

    model_config = ConfigDict(extra="forbid")

    mode: str = "managed"
    path: str | None = None


class ProjectCreate(BaseModel):
    """独立 Project 创建请求。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1, max_length=128)
    name: str
    workdir: ProjectWorkdirCreate


class ProjectUpdate(BaseModel):
    """Project 可修改字段。"""

    model_config = ConfigDict(extra="forbid")

    name: str


class ProjectRepositoryCreate(BaseModel):
    """Project 仓库绑定创建请求。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    connection_id: str = Field(min_length=1, max_length=64)
    alias: str = Field(min_length=1, max_length=80)
    repository_owner: str = Field(min_length=1, max_length=255)
    repository_name: str = Field(min_length=1, max_length=255)


@projects.get("")
async def list_projects(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户可选择的 Project。"""
    return await list_projects_view(uid=str(current_user.uid), db=db)


@projects.post("")
async def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """独立创建 managed 或 linked Project。"""
    return await create_project_view(
        uid=str(current_user.uid),
        request_id=payload.request_id,
        name=payload.name,
        directory_mode=payload.workdir.mode,
        workdir_path=payload.workdir.path,
        db=db,
    )


@projects.get("/history-candidates")
async def list_history_candidates(
    q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出可作为目录快捷选择的历史 Conversation。"""
    return await list_history_candidates_view(uid=str(current_user.uid), db=db, query=q, limit=limit, offset=offset)


@projects.put("/{project_id}")
async def rename_project(
    project_id: str,
    payload: ProjectUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """重命名当前用户的 Project。"""
    return await rename_project_view(uid=str(current_user.uid), project_id=project_id, name=payload.name, db=db)


@projects.delete("/{project_id}")
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """软删除当前用户的 Project 及其中对话。"""
    return await delete_project_view(uid=str(current_user.uid), project_id=project_id, db=db)


@projects.get("/{project_id}/repositories")
async def list_project_repositories(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出 Project 仓库绑定。"""
    return await list_project_repositories_view(uid=str(current_user.uid), project_id=project_id, db=db)


@projects.post("/{project_id}/repositories", status_code=status.HTTP_202_ACCEPTED)
async def create_project_repository(
    project_id: str,
    payload: ProjectRepositoryCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """创建仓库绑定并在事务提交后发布 provision job。"""
    result, job = await create_project_repository_view(
        uid=str(current_user.uid), project_id=project_id, db=db, **payload.model_dump()
    )
    if job:
        await enqueue_project_git_operation(*job)
    return result


@projects.post("/{project_id}/repositories/{repository_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_project_repository(
    project_id: str,
    repository_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """重试失败的仓库操作。"""
    result, job = await retry_project_repository_view(
        uid=str(current_user.uid), project_id=project_id, repository_id=repository_id, db=db
    )
    await enqueue_project_git_operation(*job)
    return result


@projects.delete("/{project_id}/repositories/{repository_id}", status_code=status.HTTP_202_ACCEPTED)
async def deactivate_project_repository(
    project_id: str,
    repository_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """停用仓库并在提交后发布撤权 job。"""
    result, job = await deactivate_project_repository_view(
        uid=str(current_user.uid), project_id=project_id, repository_id=repository_id, db=db
    )
    if job:
        await enqueue_project_git_operation(*job)
    return result


@projects.get("/{project_id}/git-worktrees")
async def list_project_worktrees(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出 Project 根任务 worktree。"""
    return await list_project_worktrees_view(uid=str(current_user.uid), project_id=project_id, db=db)


@projects.delete("/{project_id}/git-worktrees/{worktree_id}", status_code=status.HTTP_202_ACCEPTED)
async def cleanup_project_worktree(
    project_id: str,
    worktree_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """显式安全清理已推送 worktree。"""
    result, cleanup_worktree_id = await cleanup_project_worktree_view(
        uid=str(current_user.uid), project_id=project_id, worktree_id=worktree_id, db=db
    )
    if cleanup_worktree_id:
        await enqueue_project_git_worktree_cleanup(cleanup_worktree_id)
    return result
