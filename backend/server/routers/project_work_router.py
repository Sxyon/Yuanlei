"""独立项目工作任务与问题单 HTTP 入口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services import project_work_service as work
from yuxi.storage.postgres.models_business import User

project_work = APIRouter(tags=["project-work"])


class WorkCode(BaseModel):
    """项目或议题缩写配置。"""

    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=12)


class WorkTaskCreate(BaseModel):
    """项目工作任务创建请求。"""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=512)
    description: str | None = None
    topic_id: str | None = Field(default=None, max_length=64)
    parent_id: str | None = Field(default=None, max_length=64)
    primary_owner_agent_slug: str | None = Field(default=None, max_length=80)


class WorkTaskUpdate(BaseModel):
    """任务状态与第一负责人变更。"""

    model_config = ConfigDict(extra="forbid")
    status: str | None = None
    primary_owner_agent_slug: str | None = Field(default=None, max_length=80)


class WorkIssueCreate(BaseModel):
    """任务问题单创建请求。"""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=512)
    description: str | None = None


class WorkIssueUpdate(BaseModel):
    """问题单状态变更。"""

    model_config = ConfigDict(extra="forbid")
    status: str


class WorkCommentCreate(BaseModel):
    """任务或问题单评论请求。"""

    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=100_000)


class WorkReferenceCreate(BaseModel):
    """任务网页引用请求。"""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=512)
    url: str = Field(min_length=1, max_length=2048)


@project_work.get("/projects/{project_id}/work/code")
async def get_project_code(
    project_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取项目工作任务缩写。"""
    return await work.get_project_code(db=db, user=user, project_id=project_id)


@project_work.put("/projects/{project_id}/work/code")
async def configure_project_code(
    project_id: str,
    payload: WorkCode,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """固化项目缩写。"""
    return await work.configure_project_code(db=db, user=user, project_id=project_id, code=payload.code)


@project_work.put("/projects/{project_id}/work/topics/{topic_id}/code")
async def configure_topic_code(
    project_id: str,
    topic_id: str,
    payload: WorkCode,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """固化议题缩写。"""
    return await work.configure_topic_code(
        db=db, user=user, project_id=project_id, topic_id=topic_id, code=payload.code
    )


@project_work.post("/projects/{project_id}/work/tasks")
async def create_task(
    project_id: str,
    payload: WorkTaskCreate,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """创建独立项目工作任务。"""
    return await work.create_task(db=db, user=user, project_id=project_id, **payload.model_dump())


@project_work.get("/projects/{project_id}/work/tasks")
async def list_tasks(
    project_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出当前项目工作任务。"""
    return await work.list_tasks(db=db, user=user, project_id=project_id)


@project_work.get("/projects/{project_id}/work/tasks/{task_id}")
async def get_task(
    project_id: str,
    task_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取任务、问题单与讨论。"""
    return await work.get_task(db=db, user=user, project_id=project_id, task_id=task_id)


@project_work.patch("/projects/{project_id}/work/tasks/{task_id}")
async def update_task(
    project_id: str,
    task_id: str,
    payload: WorkTaskUpdate,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """更新任务状态或第一负责人。"""
    return await work.update_task(
        db=db,
        user=user,
        project_id=project_id,
        task_id=task_id,
        update_owner="primary_owner_agent_slug" in payload.model_fields_set,
        **payload.model_dump(),
    )


@project_work.post("/projects/{project_id}/work/tasks/{task_id}/references")
async def add_reference(
    project_id: str,
    task_id: str,
    payload: WorkReferenceCreate,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """追加任务网页引用。"""
    return await work.add_reference(db=db, user=user, project_id=project_id, task_id=task_id, **payload.model_dump())


@project_work.delete("/projects/{project_id}/work/tasks/{task_id}/references/{reference_id}")
async def remove_reference(
    project_id: str,
    task_id: str,
    reference_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """移除任务网页引用。"""
    return await work.remove_reference(
        db=db, user=user, project_id=project_id, task_id=task_id, reference_id=reference_id
    )


@project_work.post("/projects/{project_id}/work/tasks/{task_id}/issues")
async def create_issue(
    project_id: str,
    task_id: str,
    payload: WorkIssueCreate,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """在任务下创建独立问题单。"""
    return await work.create_issue(db=db, user=user, project_id=project_id, task_id=task_id, **payload.model_dump())


@project_work.get("/projects/{project_id}/work/tasks/{task_id}/issues/{issue_id}")
async def get_issue(
    project_id: str,
    task_id: str,
    issue_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取问题单及讨论。"""
    return await work.get_issue(db=db, user=user, project_id=project_id, task_id=task_id, issue_id=issue_id)


@project_work.patch("/projects/{project_id}/work/tasks/{task_id}/issues/{issue_id}")
async def update_issue(
    project_id: str,
    task_id: str,
    issue_id: str,
    payload: WorkIssueUpdate,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """更新问题单状态。"""
    return await work.update_issue(
        db=db, user=user, project_id=project_id, task_id=task_id, issue_id=issue_id, status=payload.status
    )


@project_work.post("/projects/{project_id}/work/tasks/{task_id}/comments")
async def add_task_comment(
    project_id: str,
    task_id: str,
    payload: WorkCommentCreate,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """追加任务评论。"""
    return await work.add_comment(db=db, user=user, project_id=project_id, task_id=task_id, content=payload.content)


@project_work.post("/projects/{project_id}/work/tasks/{task_id}/issues/{issue_id}/comments")
async def add_issue_comment(
    project_id: str,
    task_id: str,
    issue_id: str,
    payload: WorkCommentCreate,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """追加问题单评论。"""
    return await work.add_comment(
        db=db,
        user=user,
        project_id=project_id,
        task_id=task_id,
        issue_id=issue_id,
        content=payload.content,
    )
