"""用户 Agent 定时任务 HTTP 适配层。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from yuxi.services.scheduled_agent_service import (
    create_scheduled_job,
    delete_scheduled_job,
    list_scheduled_jobs,
    run_scheduled_job_now,
    update_scheduled_job,
)
from yuxi.storage.postgres.models_business import User

from server.utils.auth_middleware import get_db, get_required_user

scheduled_agents = APIRouter(prefix="/scheduled-tasks", tags=["scheduled-tasks"])


class ScheduledAgentCreate(BaseModel):
    """创建定时 Agent 请求。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    name: str = Field(..., max_length=255)
    project_id: str = Field(..., max_length=64)
    agent_slug: str = Field(..., max_length=64)
    prompt: str = Field(..., max_length=32_000)
    cron_expression: str = Field(..., max_length=100)
    timezone: str = Field(..., max_length=64)
    tool_approval_mode: str = Field("default", max_length=32)
    model_spec: str | None = Field(None, max_length=512)
    enabled: bool = True


class ScheduledAgentUpdate(BaseModel):
    """更新定时 Agent 请求。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=255)
    project_id: str | None = Field(None, max_length=64)
    agent_slug: str | None = Field(None, max_length=64)
    prompt: str | None = Field(None, max_length=32_000)
    cron_expression: str | None = Field(None, max_length=100)
    timezone: str | None = Field(None, max_length=64)
    tool_approval_mode: str | None = Field(None, max_length=32)
    model_spec: str | None = Field(None, max_length=512)
    enabled: bool | None = None

    @field_validator("enabled", mode="before")
    @classmethod
    def reject_null_enabled(cls, value):
        """拒绝把显式 null 静默解释为停用任务。"""
        if value is None:
            raise ValueError("enabled 不得为 null")
        return value


class ScheduledAgentRunNow(BaseModel):
    """立即运行的幂等请求。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")


@scheduled_agents.get("")
async def list_jobs(current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    """列出当前用户的定时 Agent。"""
    return await list_scheduled_jobs(user=current_user, db=db)


@scheduled_agents.post("")
async def create_job(
    payload: ScheduledAgentCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """创建一个用户自有的定时 Agent。"""
    return await create_scheduled_job(user=current_user, db=db, data=payload.model_dump())


@scheduled_agents.patch("/{job_id}")
async def update_job(
    job_id: str,
    payload: ScheduledAgentUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """更新定时 Agent。"""
    result = await update_scheduled_job(
        job_id=job_id,
        user=current_user,
        db=db,
        data=payload.model_dump(exclude_unset=True),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return result


@scheduled_agents.post("/{job_id}/run-now")
async def run_now(
    job_id: str,
    payload: ScheduledAgentRunNow,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """立即按任务快照创建一次独立 Conversation 和 AgentRun。"""
    result = await run_scheduled_job_now(
        job_id=job_id,
        request_id=payload.request_id,
        user=current_user,
        db=db,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return result


@scheduled_agents.delete("/{job_id}")
async def delete_job(job_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    """删除定时 Agent 定义。"""
    if not await delete_scheduled_job(job_id=job_id, user=current_user, db=db):
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return {"deleted": True, "job_id": job_id}
