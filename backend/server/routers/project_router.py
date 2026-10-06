"""Project HTTP 适配层。"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from yuxi.services.project_settings_service import (
    get_project_settings,
    update_project_settings,
    update_project_knowledge_links,
)
from yuxi.services.project_git_service import (
    cleanup_project_worktree_view,
    create_project_repository_view,
    deactivate_project_repository_view,
    list_project_repositories_view,
    list_project_worktrees_view,
    retry_project_repository_view,
    update_project_repository_policy_view,
)
from yuxi.git.executor import GitExecutionError
from yuxi.services.project_git_resource_service import (
    list_resource_branches,
    configure_project_git_resource,
    prepare_project_git_resource,
    review_project_git_resource,
    discard_project_git_resource,
)
from yuxi.services.project_git_execution_service import list_git_occupancies, release_git_occupancy
from yuxi.services.project_git_pull_request_service import (
    list_resource_pull_requests,
    create_resource_pull_request,
)
from yuxi.services.run_queue_service import (
    enqueue_project_git_operation,
    enqueue_project_git_worktree_cleanup,
)
from yuxi.services.project_git_worktree_artifact_service import operate_worktree_artifact
from yuxi.storage.postgres.models_business import User

from yuxi.services.project_git_action_service import (
    list_project_git_actions,
    decide_project_git_action,
    human_git_action,
)

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


class ProjectSettingsUpdate(BaseModel):
    """项目名称与管理属性的完整保存请求。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    work_status: Literal["planned", "in_progress", "paused", "completed", "cancelled"]
    priority: Literal["urgent", "high", "medium", "low", "none"]
    owner_type: Literal["none", "member", "agent"]
    owner_id: str | None = Field(default=None, min_length=1, max_length=80)
    description: str = Field(default="", max_length=255)
    project_type: Literal["unspecified", "ongoing", "delivery"] = "unspecified"
    category: str | None = Field(default=None, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=20)
    start_date: date | None = None
    due_date: date | None = None


class ProjectKnowledgeUpdate(BaseModel):
    """项目知识库关联完整选择。"""

    model_config = ConfigDict(extra="forbid")
    kb_ids: list[str] = Field(max_length=100)


class ProjectRepositoryCreate(BaseModel):
    """Project 仓库绑定创建请求。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    connection_id: str = Field(min_length=1, max_length=64)
    alias: str = Field(min_length=1, max_length=80)
    repository_owner: str = Field(min_length=1, max_length=255)
    repository_name: str = Field(min_length=1, max_length=255)
    purpose: str = Field(default="项目仓库", min_length=1, max_length=500)
    configured_base_branch: str | None = Field(default=None, max_length=255)
    allowed_base_branches: list[str] = Field(default_factory=list, max_length=100)
    checkout_path: str | None = Field(default=None, min_length=1, max_length=512)
    usage_mode: Literal["in_place", "worktree"] = "worktree"
    approval_mode: Literal["automatic", "protected"] = "protected"


class ProjectRepositoryPolicyUpdate(BaseModel):
    """Project 仓库任务基线策略。"""

    model_config = ConfigDict(extra="forbid")
    purpose: str = Field(min_length=1, max_length=500)
    configured_base_branch: str | None = Field(default=None, max_length=255)
    allowed_base_branches: list[str] = Field(default_factory=list, max_length=100)


class GitResourceConfigure(BaseModel):
    """分支资源的项目目录与运行、授权模式。"""

    model_config = ConfigDict(extra="forbid")
    checkout_path: str = Field(min_length=1, max_length=512)
    branch: str = Field(min_length=1, max_length=255)
    usage_mode: Literal["in_place", "worktree"]
    approval_mode: Literal["automatic", "protected"]


class GitResourceSnapshot(BaseModel):
    """用户明确确认的 HEAD 与内容树。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_head: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    expected_tree: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class GitResourceRelease(BaseModel):
    """待释放的持久任务或对话占用。"""

    model_config = ConfigDict(extra="forbid")
    scope_key: str = Field(min_length=1, max_length=191)


class GitResourceCommit(BaseModel):
    """用户确认的内容树与提交说明。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_head: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    expected_tree: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    message: str = Field(min_length=1, max_length=2000)


class GitPullRequestCreate(BaseModel):
    """人工选择任务源分支与目标分支。"""

    model_config = ConfigDict(extra="forbid")
    head_branch: str = Field(min_length=1, max_length=255)
    base_branch: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(default="", max_length=10000)


class GitPullRequestMerge(BaseModel):
    """人工确认当前源与目标提交。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_head: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    expected_base: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


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


@projects.put("/{project_id}/repositories/{repository_id}/policy")
async def update_project_repository_policy(
    project_id: str,
    repository_id: str,
    payload: ProjectRepositoryPolicyUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """验证远端分支并更新未来任务使用的仓库策略。"""
    return await update_project_repository_policy_view(
        uid=str(current_user.uid),
        project_id=project_id,
        repository_id=repository_id,
        db=db,
        **payload.model_dump(),
    )


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


@projects.get("/{project_id}/git-worktrees/{worktree_id}/review")
async def review_worktree_artifact(
    project_id: str,
    worktree_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """从可信临时镜像查看任务工作树差异。"""
    try:
        return await operate_worktree_artifact(
            db=db, uid=str(current_user.uid), project_id=project_id, worktree_id=worktree_id
        )
    except (GitExecutionError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="工作树无法安全审查，请检查分配目录与 Git 元数据") from exc


@projects.post("/{project_id}/git-worktrees/{worktree_id}/commit")
async def commit_worktree_artifact(
    project_id: str,
    worktree_id: str,
    payload: GitResourceCommit,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工确认精确快照后提交任务分支。"""
    try:
        return await human_git_action(
            db=db,
            uid=str(current_user.uid),
            project_id=project_id,
            worktree_id=worktree_id,
            action="commit",
            **payload.model_dump(),
        )
    except (GitExecutionError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="工作树提交失败或审查内容已变化，请重新审查") from exc


@projects.post("/{project_id}/git-worktrees/{worktree_id}/push")
async def push_worktree_artifact(
    project_id: str,
    worktree_id: str,
    payload: GitResourceSnapshot,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工推送已审查的干净工作树，回读实际远端 HEAD。"""
    try:
        return await human_git_action(
            db=db,
            uid=str(current_user.uid),
            project_id=project_id,
            worktree_id=worktree_id,
            action="push",
            **payload.model_dump(),
        )
    except (GitExecutionError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="工作树推送失败或远端已有进展，请重新审查") from exc


@projects.post("/{project_id}/git-worktrees/{worktree_id}/discard")
async def discard_worktree_artifact(
    project_id: str,
    worktree_id: str,
    payload: GitResourceSnapshot,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工确认后恢复工作树内容，保留忽略文件。"""
    try:
        return await operate_worktree_artifact(
            db=db,
            uid=str(current_user.uid),
            project_id=project_id,
            worktree_id=worktree_id,
            action="discard",
            **payload.model_dump(exclude={"request_id"}),
        )
    except (GitExecutionError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="工作树清理失败或审查内容已变化，请重新审查") from exc


@projects.delete("/{project_id}/git-worktrees/{worktree_id}", status_code=status.HTTP_202_ACCEPTED)
async def cleanup_project_worktree(
    project_id: str,
    worktree_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """显式安全清理已推送 worktree。"""
    try:
        result, cleanup_worktree_id = await cleanup_project_worktree_view(
            uid=str(current_user.uid), project_id=project_id, worktree_id=worktree_id, db=db
        )
    except (GitExecutionError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="工作树无法安全清理，请检查目录与分支状态") from exc
    if cleanup_worktree_id:
        await enqueue_project_git_worktree_cleanup(cleanup_worktree_id)
    return result


@projects.get("/{project_id}/settings")
async def read_project_settings(
    project_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """读取当前用户项目设置。"""
    return await get_project_settings(user=current_user, project_id=project_id, db=db)


@projects.put("/{project_id}/settings")
async def save_project_settings(
    project_id: str,
    payload: ProjectSettingsUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """保存名称、描述与管理属性。"""
    values = payload.model_dump(exclude={"name"})
    return await update_project_settings(
        user=current_user, project_id=project_id, name=payload.name, values=values, db=db
    )


@projects.put("/{project_id}/knowledge-links")
async def save_project_knowledge_links(
    project_id: str,
    payload: ProjectKnowledgeUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """保存单向弱关联，不修改读取权限。"""
    return await update_project_knowledge_links(user=current_user, project_id=project_id, kb_ids=payload.kb_ids, db=db)


@projects.get("/{project_id}/repositories/{repository_id}/branches")
async def get_git_resource_branches(
    project_id: str,
    repository_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取资源远端的真实分支候选。"""
    return await list_resource_branches(
        uid=str(current_user.uid), project_id=project_id, repository_id=repository_id, db=db
    )


@projects.put("/{project_id}/repositories/{repository_id}/resource")
async def configure_git_resource(
    project_id: str,
    repository_id: str,
    payload: GitResourceConfigure,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """配置分支资源与空目标目录。"""
    return await configure_project_git_resource(
        uid=str(current_user.uid), project_id=project_id, repository_id=repository_id, db=db, **payload.model_dump()
    )


@projects.post("/{project_id}/repositories/{repository_id}/checkout")
async def checkout_git_resource(
    project_id: str,
    repository_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """完整检出配置分支，已有内容不被覆盖。"""
    try:
        return await prepare_project_git_resource(
            uid=str(current_user.uid), project_id=project_id, repository_id=repository_id, db=db
        )
    except GitExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@projects.get("/{project_id}/repositories/{repository_id}/review")
async def review_git_resource(
    project_id: str,
    repository_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """查看当前内容与可信 HEAD 的差异。"""
    try:
        return await review_project_git_resource(
            uid=str(current_user.uid), project_id=project_id, repository_id=repository_id, db=db
        )
    except GitExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@projects.post("/{project_id}/repositories/{repository_id}/commit")
async def commit_git_resource(
    project_id: str,
    repository_id: str,
    payload: GitResourceCommit,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工确认精确差异后提交受保护资源。"""
    try:
        return await human_git_action(
            action="commit",
            uid=str(current_user.uid),
            project_id=project_id,
            repository_id=repository_id,
            db=db,
            **payload.model_dump(),
        )
    except GitExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@projects.post("/{project_id}/repositories/{repository_id}/push")
async def push_git_resource(
    project_id: str,
    repository_id: str,
    payload: GitResourceSnapshot,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工确认无未提交内容的资源 HEAD 并推送。"""
    try:
        return await human_git_action(
            action="push",
            uid=str(current_user.uid),
            project_id=project_id,
            repository_id=repository_id,
            db=db,
            **payload.model_dump(),
        )
    except GitExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@projects.post("/{project_id}/repositories/{repository_id}/discard")
async def discard_git_resource(
    project_id: str,
    repository_id: str,
    payload: GitResourceSnapshot,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工确认精确差异，在运行停止后清理未提交内容。"""
    try:
        return await discard_project_git_resource(
            uid=str(current_user.uid),
            project_id=project_id,
            repository_id=repository_id,
            db=db,
            **payload.model_dump(exclude={"request_id"}),
        )
    except GitExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@projects.get("/{project_id}/git-occupancies")
async def get_git_occupancies(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """展示项目资源排队、持续占用和执行状态。"""
    return await list_git_occupancies(db=db, uid=str(current_user.uid), project_id=project_id)


@projects.post("/{project_id}/repositories/{repository_id}/release")
async def release_git_resource(
    project_id: str,
    repository_id: str,
    payload: GitResourceRelease,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工释放已停止执行且未提交内容已处理的占用。"""
    try:
        return await release_git_occupancy(
            db=db,
            uid=str(current_user.uid),
            project_id=project_id,
            repository_id=repository_id,
            scope_key=payload.scope_key,
        )
    except GitExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@projects.get("/{project_id}/repositories/{repository_id}/pull-requests")
async def get_resource_pull_requests(
    project_id: str,
    repository_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """查看项目任务分支的真实 Gitea 合并请求。"""
    return await list_resource_pull_requests(
        uid=str(current_user.uid),
        project_id=project_id,
        repository_id=repository_id,
        db=db,
    )


@projects.post("/{project_id}/repositories/{repository_id}/pull-requests")
async def create_git_pull_request(
    project_id: str,
    repository_id: str,
    payload: GitPullRequestCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """在 Gitea 创建合并请求。"""
    return await create_resource_pull_request(
        uid=str(current_user.uid),
        project_id=project_id,
        repository_id=repository_id,
        db=db,
        **payload.model_dump(),
    )


@projects.post("/{project_id}/repositories/{repository_id}/pull-requests/{number}/merge")
async def merge_git_pull_request(
    project_id: str,
    repository_id: str,
    number: int,
    payload: GitPullRequestMerge,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工确认后由 Gitea 执行实际合并并回读结果。"""
    return await human_git_action(
        action="merge",
        uid=str(current_user.uid),
        project_id=project_id,
        repository_id=repository_id,
        number=number,
        db=db,
        **payload.model_dump(),
    )


class GitActionDecision(BaseModel):
    """人工批准或拒绝已经冻结的申请。"""

    model_config = ConfigDict(extra="forbid")
    approve: bool


@projects.get("/{project_id}/git-actions")
async def get_project_git_actions(
    project_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """分页查看 Git 批准与实际执行历史。"""
    return await list_project_git_actions(
        db=db, uid=str(current_user.uid), project_id=project_id, limit=limit, offset=offset
    )


@projects.post("/{project_id}/git-actions/{action_id}/decision")
async def decide_git_action(
    project_id: str,
    action_id: str,
    payload: GitActionDecision,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """项目所有者决定等待人工批准的 Git 快照申请。"""
    return await decide_project_git_action(
        db=db, uid=str(current_user.uid), project_id=project_id, action_id=action_id, approve=payload.approve
    )
