"""Project 数字员工的 HTTP 适配层（yuanlei 域扩展）。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services.project_agent_service import (
    bind_project_agent_view,
    create_project_agent_view,
    list_project_agents_view,
    unbind_project_agent_view,
    update_project_agent_view,
)
from yuxi.storage.postgres.models_business import User

project_agents = APIRouter(prefix="/projects/{project_id}/agents", tags=["project-agents"])


class ProjectAgentCreate(BaseModel):
    """创建项目私有智能体请求。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    backend_id: str = "ChatbotAgent"
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = None
    icon: str | None = None
    pics: list[str] | None = None
    config_json: dict | None = None


class ProjectAgentBind(BaseModel):
    """绑定已有智能体请求。"""

    model_config = ConfigDict(extra="forbid")

    agent_slug: str = Field(..., min_length=1, max_length=80)


class ProjectAgentUpdate(BaseModel):
    """更新项目覆盖层请求；reset_fields 中的字段恢复继承基础配置。"""

    model_config = ConfigDict(extra="forbid")

    config_json: dict | None = None
    reset_fields: list[str] = Field(default_factory=list, max_length=64)


@project_agents.get("")
async def list_project_agents(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出项目数字员工及其有效配置。"""
    return await list_project_agents_view(project_id=project_id, db=db, user=current_user)


@project_agents.post("")
async def create_project_agent(
    project_id: str,
    payload: ProjectAgentCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """创建私有 Agent 并绑定为项目数字员工。"""
    try:
        return await create_project_agent_view(
            project_id=project_id,
            db=db,
            user=current_user,
            **payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@project_agents.post("/bind")
async def bind_project_agent(
    project_id: str,
    payload: ProjectAgentBind,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """把已有 Agent 绑定为项目数字员工。"""
    return await bind_project_agent_view(
        project_id=project_id,
        agent_slug=payload.agent_slug,
        db=db,
        user=current_user,
    )


@project_agents.put("/{agent_slug}")
async def update_project_agent(
    project_id: str,
    agent_slug: str,
    payload: ProjectAgentUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """更新项目覆盖层。"""
    if payload.config_json is None and not payload.reset_fields:
        raise HTTPException(status_code=422, detail="config_json 与 reset_fields 不能同时为空")
    try:
        return await update_project_agent_view(
            project_id=project_id,
            agent_slug=agent_slug,
            config_json=payload.config_json or {},
            reset_fields=payload.reset_fields,
            db=db,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@project_agents.delete("/{agent_slug}")
async def unbind_project_agent(
    project_id: str,
    agent_slug: str,
    delete_agent: bool = Query(False, description="解绑后同时删除不再属于任何项目的私有 Agent"),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """解绑项目数字员工。"""
    return await unbind_project_agent_view(
        project_id=project_id,
        agent_slug=agent_slug,
        delete_agent=delete_agent,
        db=db,
        user=current_user,
    )
