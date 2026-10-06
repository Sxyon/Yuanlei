"""项目任务执行队列与数字员工工作台 HTTP 入口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services import project_work_execution_service as work
from yuxi.services.project_work_context_service import ContextInput, preview_context, history_context
from yuxi.storage.postgres.models_business import User

project_work_executions = APIRouter(tags=["project-work-executions"])


class TaskAssignment(BaseModel):
    """指定项目任务本次执行的数字员工。"""

    model_config = ConfigDict(extra="forbid")
    agent_slug: str = Field(min_length=1, max_length=80)
    context: ContextInput | None = None


class WorkQueueConfig(BaseModel):
    """项目数字员工的任务接收策略。"""

    model_config = ConfigDict(extra="forbid")
    auto_accept_work: bool
    work_default_model_spec: str | None = Field(default=None, max_length=512)


@project_work_executions.post("/projects/{project_id}/work/tasks/{task_id}/executions")
async def assign_task(
    project_id: str,
    task_id: str,
    payload: TaskAssignment,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """把任务分配给项目数字员工。"""
    return await work.assign_task(
        db=db, user=user, project_id=project_id, task_id=task_id, agent_slug=payload.agent_slug,
        context=payload.context.model_dump() if payload.context else None
    )


@project_work_executions.get("/projects/{project_id}/work/tasks/{task_id}/executions")
async def list_task_executions(
    project_id: str,
    task_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取任务执行历史。"""
    return await work.list_task_executions(db=db, user=user, project_id=project_id, task_id=task_id)


@project_work_executions.post("/projects/{project_id}/work/tasks/{task_id}/executions/{execution_id}/cancel")
async def cancel_assignment(
    project_id: str,
    task_id: str,
    execution_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """撤回一条尚未派发的分配。"""
    return await work.cancel_assignment(
        db=db, user=user, project_id=project_id, task_id=task_id, execution_id=execution_id
    )


@project_work_executions.get("/projects/{project_id}/agents/{agent_slug}/workbench")
async def get_agent_workbench(
    project_id: str,
    agent_slug: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取智能体当前、待接受、排队和最近工作。"""
    return await work.get_agent_workbench(db=db, user=user, project_id=project_id, agent_slug=agent_slug)


@project_work_executions.put("/projects/{project_id}/agents/{agent_slug}/workbench/config")
async def update_work_queue_config(
    project_id: str,
    agent_slug: str,
    payload: WorkQueueConfig,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """更新任务自动接受与默认模型。"""
    return await work.update_work_queue_config(
        db=db, user=user, project_id=project_id, agent_slug=agent_slug, **payload.model_dump()
    )


@project_work_executions.post("/projects/{project_id}/agents/{agent_slug}/workbench/{execution_id}/accept")
async def accept_task(
    project_id: str,
    agent_slug: str,
    execution_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """接受一条任务分配并加入数字员工 FIFO。"""
    return await work.accept_task(
        db=db, user=user, project_id=project_id, agent_slug=agent_slug, execution_id=execution_id
    )


@project_work_executions.post("/projects/{project_id}/work/tasks/{task_id}/context/preview")
async def preview_work_context(
    project_id: str,
    task_id: str,
    payload: ContextInput,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """预览明确选取的当次资料。"""
    return await preview_context(
        db=db, user=user, project_id=project_id, task_id=task_id, selection=payload.selection.model_dump()
    )


@project_work_executions.get("/projects/{project_id}/work/tasks/{task_id}/context/{kind}/{record_id}")
async def get_work_context(
    project_id: str,
    task_id: str,
    kind: str,
    record_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """查看尝试或委派保存的业务输入。"""
    from fastapi import HTTPException

    if kind not in {"execution", "delegation"}:
        raise HTTPException(422, detail="资料类型无效")
    return await history_context(
        db=db, user=user, project_id=project_id, task_id=task_id, kind=kind, record_id=record_id
    )
