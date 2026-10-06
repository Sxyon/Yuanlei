"""元垒外部执行器委派与渠道同步的 HTTP 适配层（yuanlei 域扩展）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.delegation.contracts import (
    ChannelUnavailableError,
    DelegationError,
    DelegationNotFoundError,
    DelegationRequest,
)
from yuxi.delegation.multica import build_multica_client_from_env
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.services.channel_sync_service import ChannelSyncService
from yuxi.services.delegation_service import DelegationService
from yuxi.storage.postgres.models_business import User
from yuxi.workspace.workdir import Workdir

delegations = APIRouter(tags=["delegations"])


class DelegationCreate(BaseModel):
    """发起一次外部执行器委派的请求。"""

    model_config = ConfigDict(extra="forbid")

    work_task_id: str = Field(..., min_length=1, max_length=64)
    executor_key: str = Field(..., max_length=32)
    task: str = Field(..., min_length=1)
    initiator_run_id: str | None = Field(None, max_length=64)
    budget: dict[str, Any] | None = None


class ProjectTaskDelegationCreate(BaseModel):
    """将已审核的项目任务交给本地执行器。"""

    model_config = ConfigDict(extra="forbid")
    executor_key: str = Field(..., pattern="^(codex|opencode)$")
    agent_slug: str | None = Field(None, max_length=80)


async def _require_project(*, project_id: str, db: AsyncSession, user: User):
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    return project


def _delegation_http_error(exc: DelegationError) -> HTTPException:
    if isinstance(exc, DelegationNotFoundError):
        status_code = 404
    elif isinstance(exc, ChannelUnavailableError):
        status_code = 503
    else:
        status_code = 409
    return HTTPException(status_code=status_code, detail={"code": exc.error_code, "message": str(exc)})


@delegations.post("/projects/{project_id}/delegations")
async def create_delegation(
    project_id: str,
    payload: DelegationCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """把任务委派给已注册的外部执行器并回收为统一委派视图。"""
    project = await _require_project(project_id=project_id, db=db, user=current_user)
    if payload.executor_key in {"codex", "opencode"}:
        raise HTTPException(
            status_code=422,
            detail={"code": "task_required", "message": "本地执行请从正式工作发起"},
        )
    service = DelegationService.build_default(db)
    if payload.executor_key not in service.registered_keys():
        raise HTTPException(
            status_code=503,
            detail={"code": "executor_unavailable", "message": f"执行器不可用: {payload.executor_key}"},
        )
    request = DelegationRequest(
        operation_id="",
        project_id=str(project.id),
        task=payload.task,
        initiator_run_id=payload.initiator_run_id,
        budget=payload.budget or {},
        metadata={"work_task_id": payload.work_task_id},
    )
    try:
        return await service.dispatch(executor_key=payload.executor_key, request=request, uid=str(current_user.uid))
    except DelegationError as exc:
        raise _delegation_http_error(exc) from exc


@delegations.post("/projects/{project_id}/governance/tasks/{task_id}/delegations")
async def delegate_project_task(
    project_id: str,
    task_id: str,
    payload: ProjectTaskDelegationCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """从已审核项目任务发起可追溯的本地编码委派。"""
    try:
        return await DelegationService.build_default(db).dispatch_project_task(
            project_id=project_id, task_id=task_id, executor_key=payload.executor_key, user=current_user
        )
    except DelegationError as exc:
        raise _delegation_http_error(exc) from exc


@delegations.post("/projects/{project_id}/work/tasks/{task_id}/delegations")
async def delegate_work_task(
    project_id: str,
    task_id: str,
    payload: ProjectTaskDelegationCreate,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """保留编码执行能力，由正式工作发起。"""
    try:
        return await DelegationService.build_default(db).dispatch_work_task(
            project_id=project_id,
            task_id=task_id,
            executor_key=payload.executor_key,
            agent_slug=payload.agent_slug,
            user=user,
        )
    except DelegationError as exc:
        raise _delegation_http_error(exc) from exc


@delegations.get("/projects/{project_id}/delegations")
async def list_delegations(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出项目内委派事实；本地状态与远端只读投影同时呈现。"""
    project = await _require_project(project_id=project_id, db=db, user=current_user)
    return await DelegationService.build_default(db).list_delegations(project_id=str(project.id))


@delegations.get("/projects/{project_id}/delegations/{operation_id}")
async def get_delegation(
    project_id: str,
    operation_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取单条委派视图并刷新远端状态的只读投影。"""
    project = await _require_project(project_id=project_id, db=db, user=current_user)
    try:
        return await DelegationService.build_default(db).status(operation_id=operation_id, project_id=str(project.id))
    except DelegationError as exc:
        raise _delegation_http_error(exc) from exc


@delegations.post("/projects/{project_id}/delegations/{operation_id}/collect")
async def collect_delegation(
    project_id: str,
    operation_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """回收委派结果，远端文本结果物化在 Project Workdir 边界内。"""
    project = await _require_project(project_id=project_id, db=db, user=current_user)
    workdir = Workdir.open_existing(str(current_user.uid), str(project.workdir_path))
    try:
        return await DelegationService.build_default(db).collect(
            operation_id=operation_id, project_id=str(project.id), workdir=workdir
        )
    except DelegationError as exc:
        raise _delegation_http_error(exc) from exc


@delegations.post("/projects/{project_id}/channels/multica/sync")
async def sync_multica_channel(
    project_id: str,
    limit: int = 50,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """显式触发一次 Multica 入向拉取，只产生 proposed 治理行。"""
    project = await _require_project(project_id=project_id, db=db, user=current_user)
    client = build_multica_client_from_env()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "channel_unavailable", "message": "Multica 渠道未配置"},
        )
    service = ChannelSyncService(db, client=client)
    try:
        return await service.pull_multica(project_id=str(project.id), actor_uid=str(current_user.uid), limit=int(limit))
    except DelegationError as exc:
        raise _delegation_http_error(exc) from exc


@delegations.get("/projects/{project_id}/channels/multica/cursor")
async def get_multica_cursor(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取 Multica 入向同步游标状态。"""
    project = await _require_project(project_id=project_id, db=db, user=current_user)
    client = build_multica_client_from_env()
    if client is None:
        raise HTTPException(status_code=503, detail={"code": "channel_unavailable", "message": "Multica 渠道未配置"})
    return await ChannelSyncService(db, client=client).get_cursor(project_id=str(project.id))
